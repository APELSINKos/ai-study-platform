"""Processing of one uploaded document, from its stored file to analysed, embedded chunks.

A run starts by claiming the document, which moves its run token, the attempts column; each
later write checks that token, so a run whose document was deleted, or claimed by a newer
run, writes nothing more and is skipped. Every database step is a short transaction of its
own, one after another, and none is open while the file is read or a provider works.
"""

import signal
import sys
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import FrameType
from typing import Final, Literal, Self

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.timing import MS_PER_SECOND
from app.documents.analysis_sample import build_analysis_sample
from app.documents.chunking import (
    Chunk,
    chunk_markdown,
    chunk_pdf_pages,
    chunk_plain,
    join_pages,
    markdown_headings,
)
from app.documents.cleaning import check_text, clean_pdf_pages, clean_text
from app.documents.errors import (
    TEXT_TOO_LONG_MESSAGE,
    DocumentProcessingError,
    ProcessingDeadlineExceeded,
)
from app.documents.extraction import ExtractedDocument, extract
from app.documents.stats import estimated_study_minutes, word_count
from app.documents.storage import FileStorage
from app.llm.base import AnalysisRequest, EmbeddingProvider, LLMProvider, ProviderError
from app.llm.mock_provider import MockLLMProvider
from app.llm.schemas import NormalizedAnalysis, normalize_analysis
from app.models.document import DocumentErrorCode
from app.repositories.document_chunks import ChunkRow, DocumentChunkRepository
from app.repositories.documents import ClaimedDocument, DocumentRepository
from app.workers.celery_app import DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS

logger = structlog.get_logger(__name__)

# A run stops itself this long before the task's soft time limit, which leaves it time to
# record why it stopped.
DEADLINE_MARGIN_SECONDS: Final = 60
_RUN_TIME_LIMIT: Final = timedelta(
    seconds=DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS - DEADLINE_MARGIN_SECONDS
)
# A document within the character limit can still be tens of thousands of tiny sections,
# each a chunk to embed and store.
MAX_CHUNKS_PER_DOCUMENT: Final = 5000

_FILE_MISSING_MESSAGE: Final = "The original file of the document is no longer stored."
_TIMEOUT_MESSAGE: Final = "Processing the document took longer than allowed."
# Followed by the type of the error alone: its text could be long or hold document text.
_INTERNAL_ERROR_MESSAGE: Final = "Processing stopped on an unexpected error"

type OutcomeKind = Literal["ready", "failed", "skipped", "retry"]
# not_claimable: the document is gone, or it was not waiting for processing.
# superseded: it was deleted, or claimed by a newer run, while this run worked on it.
type SkipReason = Literal["not_claimable", "superseded"]


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """How a run ended: the document is ready, failed, waiting for a retry, or was skipped."""

    kind: OutcomeKind
    chunk_count: int | None = None
    code: DocumentErrorCode | None = None
    retry_after_seconds: float | None = None
    reason: SkipReason | None = None

    @classmethod
    def ready(cls, chunk_count: int) -> Self:
        return cls("ready", chunk_count=chunk_count)

    @classmethod
    def failed(cls, code: DocumentErrorCode) -> Self:
        return cls("failed", code=code)

    @classmethod
    def skipped(cls, reason: SkipReason) -> Self:
        return cls("skipped", reason=reason)

    @classmethod
    def retry(cls, code: DocumentErrorCode, retry_after_seconds: float | None) -> Self:
        return cls("retry", code=code, retry_after_seconds=retry_after_seconds)


def run_pipeline(  # noqa: PLR0913 -- every dependency is passed in, so a test can replace any
    document_id: uuid.UUID,
    *,
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    settings: Settings,
    clock: Callable[[], datetime],
    final_attempt: bool,
) -> PipelineOutcome:
    """Process the document if it is waiting for processing, and say how the run ended.

    The run records every failure on the document itself. A provider that is only
    unavailable leaves the document waiting for another attempt, unless final_attempt says
    that none will follow; then the document fails.
    """
    claimed_at = clock()
    with session_factory.begin() as session:
        document = DocumentRepository(session).claim_for_processing(document_id, claimed_at)
    if document is None:
        return PipelineOutcome.skipped("not_claimable")
    run = _Run(
        document=document,
        claimed_at=claimed_at,
        session_factory=session_factory,
        storage=storage,
        llm=llm,
        embedder=embedder,
        settings=settings,
        clock=clock,
        final_attempt=final_attempt,
    )
    return run.process()


class _RunSupersededError(Exception):
    """The run's document was deleted, or claimed by a newer run, while it worked."""


@dataclass(frozen=True, slots=True)
class _DocumentText:
    """A document's cleaned text, its headings, its chunks and, for a PDF, its page count."""

    text: str
    headings: list[str]
    chunks: list[Chunk]
    page_count: int | None


@dataclass(frozen=True, slots=True)
class _Run:
    """One processing run of a claimed document, with everything it works with."""

    document: ClaimedDocument
    claimed_at: datetime
    session_factory: sessionmaker[Session]
    storage: FileStorage
    llm: LLMProvider
    embedder: EmbeddingProvider
    settings: Settings
    clock: Callable[[], datetime]
    final_attempt: bool

    def process(self) -> PipelineOutcome:
        try:
            text = self._read()
            analysis, model = self._analyse(text)
            self._save_analysis(text, analysis, model)
            vectors = self._embed(text.chunks)
            return self._complete(text.chunks, vectors)
        except _RunSupersededError:
            return PipelineOutcome.skipped("superseded")
        except (ProcessingDeadlineExceeded, SoftTimeLimitExceeded):
            # Written in a session of its own: the step that ran out of time rolled back.
            return self._fail("processing_timeout", _TIMEOUT_MESSAGE)
        except DocumentProcessingError as error:
            return self._fail(error.code, error.message)
        except ProviderError as error:
            return self._provider_failed(error)
        except Exception as error:
            logger.exception("document_processing_crashed", document_id=str(self.document.id))
            message = f"{_INTERNAL_ERROR_MESSAGE}: {type(error).__name__}."
            return self._fail("internal_error", message)

    def _read(self) -> _DocumentText:
        """Extract, clean, check and chunk the text of the stored file."""
        path = self.storage.path_for(self.document.storage_key)
        if not path.is_file():
            raise DocumentProcessingError("file_missing", _FILE_MISSING_MESSAGE)
        settings = self.settings
        with _deadline_alarm(self._seconds_left()):
            extracted = extract(
                path,
                self.document.content_type,
                max_pdf_pages=settings.max_pdf_pages,
                max_chars=settings.max_document_chars,
                check_deadline=self._check_deadline,
            )
        text, pages = _cleaned(extracted)
        check_text(text, max_chars=settings.max_document_chars)
        size, overlap = settings.chunk_size_chars, settings.chunk_overlap_chars
        headings: list[str] = []
        if pages is not None:
            chunks = chunk_pdf_pages(pages, size=size, overlap=overlap)
        elif self.document.content_type == "text/markdown":
            chunks = chunk_markdown(text, size=size, overlap=overlap)
            headings = markdown_headings(text)
        else:
            chunks = chunk_plain(text, size=size, overlap=overlap)
        if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
            raise DocumentProcessingError("text_too_long", TEXT_TOO_LONG_MESSAGE)
        return _DocumentText(
            text=text, headings=headings, chunks=chunks, page_count=extracted.page_count
        )

    def _analyse(self, text: _DocumentText) -> tuple[NormalizedAnalysis, str]:
        """The document's analysis and the name of the model that made it.

        An analysis that an earlier attempt saved with the same model is used again, so a
        retry never pays for a second one. A model that refuses the document for good is
        replaced by the heuristic analysis; one that is only unavailable is not.
        """
        self._check_deadline()
        saved = _saved_analysis(self.document)
        if saved is not None and self.document.analysis_model == self.llm.model_name:
            return saved, self.llm.model_name
        outline, sample = build_analysis_sample(
            text.text, text.headings, self.settings.analysis_max_input_chars
        )
        request = AnalysisRequest(
            filename=self.document.original_filename, outline=outline, sample=sample
        )
        try:
            result = self.llm.analyze_document(request)
        except ProviderError as error:
            if error.transient:
                raise
            logger.warning(
                "document_analysis_fell_back",
                document_id=str(self.document.id),
                error_code=error.code,
                error_message=error.message,
            )
            result = MockLLMProvider().analyze_document(request)
        return normalize_analysis(result.analysis), result.model

    def _save_analysis(self, text: _DocumentText, analysis: NormalizedAnalysis, model: str) -> None:
        """Store the analysis with the document's counts and move it on to indexing."""
        words = word_count(text.text)
        with self.session_factory.begin() as session:
            saved = DocumentRepository(session).update_if_current(
                self.document.id,
                self.document.token,
                self.clock(),
                status="indexing",
                error_code=None,
                error_message=None,
                title=analysis.title,
                summary=analysis.summary,
                topics=analysis.topics,
                difficulty=analysis.difficulty,
                analysis_model=model,
                estimated_study_minutes=estimated_study_minutes(words, analysis.difficulty),
                word_count=words,
                page_count=text.page_count,
            )
        if not saved:
            raise _RunSupersededError

    def _embed(self, chunks: list[Chunk]) -> list[list[float]]:
        """A vector for each chunk, embedded a batch at a time."""
        texts = [chunk.content for chunk in chunks]
        batch_size = self.settings.embedding_batch_size
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            self._check_deadline()
            vectors.extend(self.embedder.embed(texts[start : start + batch_size]))
        return vectors

    def _complete(self, chunks: list[Chunk], vectors: list[list[float]]) -> PipelineOutcome:
        """Mark the document ready and store its chunks, both in one transaction."""
        rows = [
            ChunkRow(
                chunk_index=chunk.index,
                content=chunk.content,
                heading=chunk.heading,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                char_count=chunk.char_count,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        finished_at = self.clock()
        with self.session_factory.begin() as session:
            # The document row is locked before its chunks, the order in which a delete of
            # the document locks them through its cascade; the opposite order could deadlock.
            completed = DocumentRepository(session).complete(
                self.document.id,
                self.document.token,
                finished_at,
                chunk_count=len(rows),
                embedding_model=self.embedder.model_name,
                processing_ms=_elapsed_ms(self.claimed_at, finished_at),
            )
            if not completed:
                # Leaving the block with an error rolls the transaction back.
                raise _RunSupersededError
            DocumentChunkRepository(session).replace_for_document(
                self.document.id, self.document.workspace_id, rows
            )
        return PipelineOutcome.ready(len(rows))

    def _provider_failed(self, error: ProviderError) -> PipelineOutcome:
        """Wait for another attempt after an unavailable provider, unless this was the last.

        Any other provider error fails the document with its code.
        """
        # Provider errors carry no cause, so their code and message say all there is.
        logger.warning(
            "document_provider_failed",
            document_id=str(self.document.id),
            error_code=error.code,
            error_message=error.message,
            transient=error.transient,
        )
        if error.transient and not self.final_attempt:
            return self._retry_later(error)
        return self._fail(error.code, error.message)

    def _fail(self, code: DocumentErrorCode, message: str) -> PipelineOutcome:
        """Record the error on the document, which ends as failed."""
        with self.session_factory.begin() as session:
            failed = DocumentRepository(session).mark_failed(
                self.document.id, self.document.token, code, message, self.clock()
            )
        return PipelineOutcome.failed(code) if failed else PipelineOutcome.skipped("superseded")

    def _retry_later(self, error: ProviderError) -> PipelineOutcome:
        """Leave the document waiting, with the error, for the task's next attempt."""
        with self.session_factory.begin() as session:
            pending = DocumentRepository(session).mark_retry_pending(
                self.document.id, self.document.token, error.code, error.message, self.clock()
            )
        if not pending:
            return PipelineOutcome.skipped("superseded")
        return PipelineOutcome.retry(error.code, error.retry_after_seconds)

    def _check_deadline(self) -> None:
        if self.clock() >= self.claimed_at + _RUN_TIME_LIMIT:
            raise ProcessingDeadlineExceeded

    def _seconds_left(self) -> float:
        return (self.claimed_at + _RUN_TIME_LIMIT - self.clock()).total_seconds()


@contextmanager
def _deadline_alarm(seconds: float) -> Iterator[None]:
    """Raise ProcessingDeadlineExceeded once seconds have passed, whatever code is running.

    pypdf checks no deadline while it repairs a damaged file, which can take minutes. A
    signal handler can still raise there; it needs a POSIX system and the main thread, the
    one a worker child runs its tasks in. Elsewhere only the deadline checks remain.
    """
    if seconds <= 0:
        raise ProcessingDeadlineExceeded
    if sys.platform == "win32" or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.signal(signal.SIGALRM, _raise_deadline_exceeded)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        # Off before the previous handler is back: by default the signal ends the process.
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _raise_deadline_exceeded(_signum: int, _frame: FrameType | None) -> None:
    raise ProcessingDeadlineExceeded


def _saved_analysis(document: ClaimedDocument) -> NormalizedAnalysis | None:
    """The analysis an earlier attempt stored on the document, if there is one."""
    if document.analysis_model is None or document.difficulty is None:
        return None
    return NormalizedAnalysis(
        title=document.title,
        summary=document.summary,
        topics=document.topics or [],
        difficulty=document.difficulty,
    )


def _cleaned(extracted: ExtractedDocument) -> tuple[str, list[str] | None]:
    """The cleaned text, with the cleaned pages of a PDF; None for the pages of other files."""
    if extracted.pages is not None:
        pages = clean_pdf_pages(extracted.pages)
        return join_pages(pages), pages
    # Every other file is extracted as one text.
    return clean_text(extracted.text or ""), None


def _elapsed_ms(start: datetime, end: datetime) -> int:
    # A wall clock can be set back, and the column takes no negative time.
    return max(0, round((end - start).total_seconds() * MS_PER_SECOND))
