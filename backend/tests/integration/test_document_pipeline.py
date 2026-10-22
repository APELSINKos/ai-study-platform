import hashlib
import io
import json
import math
import re
import signal
import sys
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from pypdf import PdfReader, PdfWriter
from sqlalchemy import Connection, delete, event, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.logging import configure_logging
from app.documents.chunking import Chunk, chunk_markdown
from app.documents.errors import ProcessingDeadlineExceeded
from app.documents.extraction import ExtractedDocument, extract
from app.documents.pipeline import (
    DEADLINE_MARGIN_SECONDS,
    MAX_CHUNKS_PER_DOCUMENT,
    PipelineOutcome,
    run_pipeline,
)
from app.documents.stats import estimated_study_minutes, word_count
from app.documents.storage import FileStorage
from app.documents.validation import content_type_for
from app.llm.base import (
    AnalysisRequest,
    AnalysisResult,
    EmbeddingProvider,
    LLMProvider,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.llm.mock_provider import (
    MOCK_ANALYSIS_MODEL,
    MOCK_EMBEDDING_MODEL,
    HashingEmbeddingProvider,
    MockLLMProvider,
)
from app.llm.schemas import DocumentAnalysis
from app.models.document import (
    DIFFICULTIES,
    ERROR_MESSAGE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    Document,
    DocumentErrorCode,
)
from app.models.document_chunk import (
    CHUNK_HEADING_MAX_LENGTH,
    EMBEDDING_DIMENSIONS,
    DocumentChunk,
)
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.document_chunks import DocumentChunkRepository
from app.repositories.documents import ClaimedDocument, DocumentRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.workers.celery_app import DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS
from tests.fixtures.pdf_builder import broken_pdf, slow_to_repair_pdf, text_pdf

pytestmark = pytest.mark.integration

_START: Final = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
_UPLOADED_AT: Final = _START - timedelta(minutes=1)
_LECTURE_PDF: Final = Path(__file__).resolve().parents[1] / "fixtures" / "lecture-ru.pdf"
_LECTURE_HEADER: Final = "Базы данных — конспект лекций"
_PAGE_NUMBER_LINE: Final = re.compile(r"^Стр\. \d+$", re.MULTILINE)
_FAKE_CHAT_MODEL: Final = "fake-chat-v1"
_BUSY: Final = "The AI provider is busy or failing: HTTP 503."
# How long after its claim a run may go on before it stops itself.
_RUN_TIME_LIMIT: Final = timedelta(
    seconds=DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS - DEADLINE_MARGIN_SECONDS
)
# pypdf takes about ten seconds to open a damaged file this big, without a deadline check.
_SLOW_TO_REPAIR_PDF_BYTES: Final = 48 * 1024
_NEEDS_ALARM: Final = pytest.mark.skipif(
    sys.platform == "win32", reason="the deadline alarm uses SIGALRM, which Windows lacks"
)
# Savepoints, which mark each session's transaction here, and the start of other statements.
_RECORDED_STATEMENT: Final = re.compile(
    r"(?:RELEASE |ROLLBACK TO )?SAVEPOINT|(?:SELECT|INSERT INTO|UPDATE|DELETE FROM) \w+"
)
_MARKDOWN: Final = """# Sorting algorithms

Sorting puts the items of a list in order. Every search over sorted data gets faster.

## Merge sort

Merge sort splits the list in half, sorts each half and merges the two sorted halves.

## Quick sort

Quick sort picks a pivot and moves smaller items before it and larger items after it."""
_HEADINGS: Final = [
    "Sorting algorithms",
    "Sorting algorithms \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Merge sort",
    "Sorting algorithms \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Quick sort",
]
_PLAIN_TEXT: Final = (
    "Spaced repetition brings each card back just before it would be forgotten.\n"
    "Short sessions on many days beat one long session the night before the exam."
)


class _FakeClock:
    """A callable clock whose time only moves when told to."""

    def __init__(self, start: datetime = _START) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def move_to(self, moment: datetime) -> None:
        self._now = moment


def _nothing() -> None:
    return None


class _FakeLLM:
    """The offline analysis under another model name; raises the given errors first.

    before_call runs at the start of every call, while the pipeline waits for the answer.
    """

    def __init__(
        self,
        *errors: BaseException,
        analysis: DocumentAnalysis | None = None,
        model: str = _FAKE_CHAT_MODEL,
        before_call: Callable[[], None] = _nothing,
    ) -> None:
        self.calls = 0
        self.requests: list[AnalysisRequest] = []
        self._errors = list(errors)
        self._analysis = analysis
        self._model = model
        self._before_call = before_call

    @property
    def model_name(self) -> str:
        return self._model

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult:
        self.calls += 1
        self.requests.append(request)
        self._before_call()
        if self._errors:
            raise self._errors.pop(0)
        analysis = self._analysis or MockLLMProvider().analyze_document(request).analysis
        return AnalysisResult(
            analysis=analysis, model=self._model, prompt_tokens=120, completion_tokens=40
        )


class _FakeEmbedder:
    """The offline embeddings, under their own model name; raises the given errors first.

    before_call runs at the start of every call, while the pipeline waits for the vectors.
    """

    def __init__(self, *errors: BaseException, before_call: Callable[[], None] = _nothing) -> None:
        self.batches: list[int] = []
        self._errors = list(errors)
        self._before_call = before_call

    @property
    def model_name(self) -> str:
        return MOCK_EMBEDDING_MODEL

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(len(texts))
        self._before_call()
        if self._errors:
            raise self._errors.pop(0)
        return HashingEmbeddingProvider().embed(texts)


@dataclass
class _Runner:
    """Stores documents and runs the pipeline on them, with the test's database and clock."""

    session: Session
    session_factory: sessionmaker[Session]
    storage: FileStorage
    settings: Settings
    clock: _FakeClock

    def store(self, content: bytes | None, filename: str, **values: object) -> Document:
        """A committed uploaded document whose file holds content; None stores no file."""
        owner = UserRepository(self.session).add(
            User(
                email=f"{uuid.uuid4().hex}@example.com",
                password_hash="hash",
                display_name="Owner",
            )
        )
        workspace = WorkspaceRepository(self.session).add(
            Workspace(owner_id=owner.id, name="Algorithms")
        )
        document_id = uuid.uuid4()
        key = self.storage.key_for(workspace.id, document_id, Path(filename).suffix)
        if content is not None:
            path = self.storage.path_for(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        fields: dict[str, object] = {
            "id": document_id,
            "workspace_id": workspace.id,
            "original_filename": filename,
            "content_type": content_type_for(filename),
            "size_bytes": len(content or b"lost"),
            "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
            "storage_key": key,
            "status": "uploaded",
            "created_at": _UPLOADED_AT,
            "updated_at": _UPLOADED_AT,
        }
        fields.update(values)
        document = DocumentRepository(self.session).add(Document(**fields))
        self.session.commit()
        return document

    def run(
        self,
        document_id: uuid.UUID,
        *,
        llm: LLMProvider | None = None,
        embedder: EmbeddingProvider | None = None,
        final_attempt: bool = False,
    ) -> PipelineOutcome:
        return run_pipeline(
            document_id,
            session_factory=self.session_factory,
            storage=self.storage,
            llm=MockLLMProvider() if llm is None else llm,
            embedder=HashingEmbeddingProvider() if embedder is None else embedder,
            settings=self.settings,
            clock=self.clock,
            final_attempt=final_attempt,
        )


def _chunks(session: Session, document_id: uuid.UUID) -> list[DocumentChunk]:
    chunks, _ = DocumentChunkRepository(session).list_for_document(
        document_id, offset=0, limit=100_000
    )
    return chunks


def _embeddings(session: Session, document_id: uuid.UUID) -> list[list[float]]:
    statement = (
        select(DocumentChunk.embedding)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(session.scalars(statement))


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(math.fsum(value * value for value in vector))


def _encrypted(pdf: bytes) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    writer.encrypt(user_password="secret", owner_password="owner", algorithm="AES-256")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _sections(count: int) -> str:
    """Markdown of count one-sentence sections, a chunk each."""
    return "\n\n".join(f"## Section {number}\n\nNote {number}." for number in range(count))


def _providers(stage: str, error: BaseException) -> tuple[_FakeLLM, _FakeEmbedder]:
    """Providers of which the one for this stage, analysis or embeddings, raises error."""
    if stage == "analysis":
        return _FakeLLM(error), _FakeEmbedder()
    return _FakeLLM(), _FakeEmbedder(error)


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def _claim_again(session: Session, document: Document) -> Callable[[], None]:
    """A callback with which a newer run claims the document, as a stale retry would."""

    def claim_again() -> None:
        session.execute(
            update(Document)
            .where(Document.id == document.id)
            .values(attempts=Document.attempts + 1)
            .execution_options(synchronize_session=False)
        )
        session.commit()

    return claim_again


def _delete(session: Session, document: Document) -> Callable[[], None]:
    """A callback with which the owner deletes the document."""

    def delete_document() -> None:
        session.execute(
            delete(Document)
            .where(Document.id == document.id)
            .execution_options(synchronize_session=False)
        )
        session.commit()

    return delete_document


def _assert_failed_before_analysis(
    session: Session, document: Document, code: DocumentErrorCode, llm: _FakeLLM
) -> None:
    session.refresh(document)
    assert (document.status, document.error_code, document.attempts) == ("failed", code, 1)
    assert document.error_message
    assert document.updated_at == _START
    assert (document.title, document.analysis_model, document.chunk_count) == (None, None, None)
    assert _chunks(session, document.id) == []
    assert llm.calls == 0


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock()


@pytest.fixture
def storage(integration_settings: Settings) -> FileStorage:
    return FileStorage(integration_settings.storage_dir)


@pytest.fixture
def runner(
    db_session: Session,
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    integration_settings: Settings,
    clock: _FakeClock,
) -> _Runner:
    return _Runner(db_session, session_factory, storage, integration_settings, clock)


def test_the_session_factory_lets_only_one_session_be_open_at_a_time(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory(), pytest.raises(pytest.fail.Exception):
        session_factory()
    # Once the first one is closed, the next one may open.
    with session_factory.begin() as session:
        assert session.execute(select(1)).scalar_one() == 1


def test_a_markdown_document_becomes_ready_with_analysed_and_embedded_chunks(
    db_session: Session, runner: _Runner, clock: _FakeClock
) -> None:
    # Waiting for a retry after an earlier attempt found the AI provider busy.
    document = runner.store(
        _MARKDOWN.encode(),
        "sorting.md",
        attempts=1,
        error_code="ai_unavailable",
        error_message="The AI provider is busy.",
    )
    embedder = _FakeEmbedder(before_call=lambda: clock.advance(timedelta(seconds=1.5)))

    outcome = runner.run(document.id, embedder=embedder)

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    db_session.refresh(document)
    assert (document.status, document.error_code, document.error_message) == ("ready", None, None)
    assert document.attempts == 2
    assert document.title == "Sorting algorithms"
    assert document.summary
    assert document.topics
    assert document.difficulty in DIFFICULTIES
    assert document.difficulty is not None
    assert document.word_count == word_count(_MARKDOWN)
    assert document.estimated_study_minutes == estimated_study_minutes(
        word_count(_MARKDOWN), document.difficulty
    )
    assert document.page_count is None
    assert document.chunk_count == 3
    assert (document.analysis_model, document.embedding_model) == (
        MOCK_ANALYSIS_MODEL,
        MOCK_EMBEDDING_MODEL,
    )
    assert document.processing_started_at == _START
    assert document.processed_at == document.updated_at == _START + timedelta(seconds=1.5)
    assert document.processing_ms == 1500
    chunks = _chunks(db_session, document.id)
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert [chunk.heading for chunk in chunks] == _HEADINGS
    assert chunks[1].content.startswith("Merge sort splits the list in half")
    assert all(chunk.char_count == len(chunk.content) for chunk in chunks)
    assert all(chunk.page_start is None and chunk.page_end is None for chunk in chunks)
    embeddings = _embeddings(db_session, document.id)
    expected = HashingEmbeddingProvider().embed([chunk.content for chunk in chunks])
    for stored, fresh in zip(embeddings, expected, strict=True):
        assert len(stored) == EMBEDDING_DIMENSIONS
        assert _norm(stored) == pytest.approx(1.0, abs=1e-5)
        # Stored as float32, so the same vector up to rounding.
        assert math.fsum(a * b for a, b in zip(stored, fresh, strict=True)) == pytest.approx(
            1.0, abs=1e-5
        )
    assert embedder.batches == [3]


def test_the_russian_lecture_pdf_becomes_ready_with_page_ranges_and_no_running_lines(
    db_session: Session, runner: _Runner
) -> None:
    page_count = len(PdfReader(_LECTURE_PDF).pages)
    document = runner.store(_LECTURE_PDF.read_bytes(), "lecture-ru.pdf")

    outcome = runner.run(document.id)

    db_session.refresh(document)
    chunks = _chunks(db_session, document.id)
    assert outcome == PipelineOutcome.ready(chunk_count=len(chunks))
    assert document.status == "ready"
    assert document.page_count == page_count >= 4
    assert document.chunk_count == len(chunks) > 1
    assert document.title == "Лекция 4. Нормализация реляционных баз данных"
    assert all(chunk.heading is None for chunk in chunks)
    ranges = [(chunk.page_start, chunk.page_end) for chunk in chunks]
    assert ranges[0][0] == 1
    assert ranges[-1][1] == page_count
    for start, end in ranges:
        assert start is not None
        assert end is not None
        assert 1 <= start <= end <= page_count
    assert ranges == sorted(ranges)
    for chunk in chunks:
        assert _LECTURE_HEADER not in chunk.content
        assert _PAGE_NUMBER_LINE.search(chunk.content) is None
    # Lines the layout wrapped are joined, at the end of a page too.
    text = " ".join(chunk.content for chunk in chunks)
    assert "схемы базы данных, при котором каждая таблица" in text
    assert "Если ключ состоит из нескольких столбцов, " in text


def test_the_model_reads_a_pdf_without_the_line_breaks_of_its_layout(runner: _Runner) -> None:
    document = runner.store(_LECTURE_PDF.read_bytes(), "lecture-ru.pdf")
    llm = _FakeLLM()

    runner.run(document.id, llm=llm)

    [request] = llm.requests
    assert "схемы базы данных, при котором каждая таблица" in request.sample
    assert "Если ключ состоит из нескольких столбцов, " in request.sample


def test_the_outline_of_a_long_markdown_document_lists_its_headings(
    runner: _Runner, integration_settings: Settings
) -> None:
    markdown = "\n\n".join(
        [
            "# Sorting algorithms",
            "## Merge sort",
            "```python\n# split the list in half\nmerge(left, right)\n```",
            "Merge sort splits the list in half and merges the sorted halves. " * 10,
            "## Quick sort",
            "Quick sort picks a pivot and moves the other items around it. " * 10,
        ]
    )
    # Too long to be sent whole, so the model gets an outline and excerpts.
    integration_settings.analysis_max_input_chars = len(markdown) // 2
    document = runner.store(markdown.encode(), "sorting.md")
    llm = _FakeLLM()

    runner.run(document.id, llm=llm)

    [request] = llm.requests
    assert request.outline == "Sorting algorithms\nMerge sort\nQuick sort"


def test_a_plain_text_document_becomes_ready_without_headings_or_pages(
    db_session: Session, runner: _Runner
) -> None:
    document = runner.store(_PLAIN_TEXT.encode(), "spacing.txt")

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.ready(chunk_count=1)
    db_session.refresh(document)
    assert (document.status, document.chunk_count, document.page_count) == ("ready", 1, None)
    assert document.word_count == word_count(_PLAIN_TEXT)
    [chunk] = _chunks(db_session, document.id)
    assert chunk.content == _PLAIN_TEXT
    assert (chunk.heading, chunk.page_start, chunk.page_end) == (None, None, None)


def test_superscripts_subscripts_and_fractions_are_stored_as_written(
    db_session: Session, runner: _Runner
) -> None:
    # Stored text is NFC: NFKC would turn them into x2, H2O and 1/2 with a fraction slash.
    text = (
        "The area grows as x\N{SUPERSCRIPT TWO}, water is H\N{SUBSCRIPT TWO}O"
        " and the recipe takes \N{VULGAR FRACTION ONE HALF} cup."
    )
    document = runner.store(text.encode(), "formulas.txt")

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.ready(chunk_count=1)
    [chunk] = _chunks(db_session, document.id)
    assert chunk.content == text


def test_a_clock_set_back_during_the_run_records_no_negative_processing_time(
    db_session: Session, runner: _Runner, clock: _FakeClock
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    # The wall clock is set back while the chunks are embedded.
    embedder = _FakeEmbedder(before_call=lambda: clock.advance(timedelta(seconds=-5)))

    outcome = runner.run(document.id, embedder=embedder)

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    db_session.refresh(document)
    assert (document.status, document.processing_ms) == ("ready", 0)


@pytest.mark.parametrize("status", ["processing", "indexing", "ready", "failed"])
def test_a_document_that_is_not_waiting_for_processing_is_skipped_untouched(
    db_session: Session, runner: _Runner, status: str
) -> None:
    # Such as a message delivered twice, or one for a document a run already owns.
    values: dict[str, object] = {"status": status, "attempts": 1}
    if status == "ready":
        values |= {
            "chunk_count": 0,
            "embedding_model": MOCK_EMBEDDING_MODEL,
            "processed_at": _START,
        }
    if status == "failed":
        values["error_code"] = "no_text"
    document = runner.store(_MARKDOWN.encode(), "sorting.md", **values)
    llm = _FakeLLM()

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.skipped("not_claimable")
    assert llm.calls == 0
    db_session.refresh(document)
    assert (document.status, document.attempts, document.updated_at) == (
        status,
        1,
        _UPLOADED_AT,
    )


def test_a_document_that_does_not_exist_is_skipped(runner: _Runner) -> None:
    assert runner.run(uuid.uuid4()) == PipelineOutcome.skipped("not_claimable")


@pytest.mark.parametrize(
    ("content", "filename", "code"),
    [
        (_encrypted(text_pdf([["Private notes."]])), "private.pdf", "pdf_encrypted"),
        (broken_pdf(), "broken.pdf", "pdf_unreadable"),
        (b"   \n\n\t \n", "blank.txt", "no_text"),
        (b"## ...\n\n---\n\n- * -\n", "marks.md", "no_text"),
    ],
    ids=["encrypted", "junk-pdf", "whitespace", "no-letters"],
)
def test_a_file_that_cannot_be_processed_fails_with_its_error_before_any_analysis(
    db_session: Session,
    runner: _Runner,
    content: bytes,
    filename: str,
    code: DocumentErrorCode,
) -> None:
    document = runner.store(content, filename)
    llm = _FakeLLM()

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.failed(code)
    _assert_failed_before_analysis(db_session, document, code, llm)


def test_a_pdf_with_more_pages_than_allowed_fails(
    db_session: Session, runner: _Runner, integration_settings: Settings
) -> None:
    integration_settings.max_pdf_pages = 2
    pdf = text_pdf([[f"Page {number} of the notes."] for number in range(1, 4)])
    document = runner.store(pdf, "notes.pdf")
    llm = _FakeLLM()

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.failed("too_many_pages")
    _assert_failed_before_analysis(db_session, document, "too_many_pages", llm)


def test_a_document_with_more_text_than_allowed_fails(
    db_session: Session, runner: _Runner, integration_settings: Settings
) -> None:
    integration_settings.max_document_chars = len(_PLAIN_TEXT) - 1
    document = runner.store(_PLAIN_TEXT.encode(), "spacing.txt")
    llm = _FakeLLM()

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.failed("text_too_long")
    _assert_failed_before_analysis(db_session, document, "text_too_long", llm)


def test_a_document_whose_file_is_gone_fails_as_file_missing(
    db_session: Session, runner: _Runner
) -> None:
    document = runner.store(None, "sorting.md")
    llm = _FakeLLM()

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.failed("file_missing")
    _assert_failed_before_analysis(db_session, document, "file_missing", llm)


def test_a_document_split_into_more_chunks_than_allowed_fails_before_any_embedding(
    db_session: Session, runner: _Runner
) -> None:
    # Far below the character limit, yet a chunk for every tiny section.
    markdown = _sections(MAX_CHUNKS_PER_DOCUMENT + 1)
    document = runner.store(markdown.encode(), "outline.md")
    llm = _FakeLLM()
    embedder = _FakeEmbedder()

    outcome = runner.run(document.id, llm=llm, embedder=embedder)

    assert outcome == PipelineOutcome.failed("text_too_long")
    _assert_failed_before_analysis(db_session, document, "text_too_long", llm)
    assert embedder.batches == []


def test_a_document_with_as_many_chunks_as_allowed_is_processed(
    runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.documents.pipeline.MAX_CHUNKS_PER_DOCUMENT", 3)
    document = runner.store(_sections(3).encode(), "outline.md")

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.ready(chunk_count=3)


@pytest.mark.parametrize("stage", ["analysis", "embeddings"])
@pytest.mark.parametrize("retry_after", [12.5, None], ids=["retry-after", "no-retry-after"])
def test_an_unavailable_provider_leaves_the_document_waiting_for_another_attempt(
    db_session: Session,
    runner: _Runner,
    stage: str,
    retry_after: float | None,
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    llm, embedder = _providers(
        stage, ProviderUnavailableError(_BUSY, retry_after_seconds=retry_after)
    )

    outcome = runner.run(document.id, llm=llm, embedder=embedder)

    assert outcome == PipelineOutcome.retry("ai_unavailable", retry_after)
    db_session.refresh(document)
    assert (
        document.status,
        document.error_code,
        document.error_message,
        document.attempts,
        document.updated_at,
    ) == ("uploaded", "ai_unavailable", _BUSY, 1, _START)
    assert document.chunk_count is None
    assert _chunks(db_session, document.id) == []


@pytest.mark.parametrize("stage", ["analysis", "embeddings"])
def test_on_the_final_attempt_an_unavailable_provider_fails_the_document(
    db_session: Session, runner: _Runner, stage: str
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    llm, embedder = _providers(stage, ProviderUnavailableError(_BUSY))

    outcome = runner.run(document.id, llm=llm, embedder=embedder, final_attempt=True)

    assert outcome == PipelineOutcome.failed("ai_unavailable")
    db_session.refresh(document)
    assert (document.status, document.error_code, document.error_message) == (
        "failed",
        "ai_unavailable",
        _BUSY,
    )
    assert _chunks(db_session, document.id) == []


def test_a_provider_failure_is_logged_with_its_code_and_message_only(
    runner: _Runner, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", "json")
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    embedder = _FakeEmbedder(ProviderUnavailableError(_BUSY, retry_after_seconds=30.0))

    runner.run(document.id, embedder=embedder)

    [warning] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "document_provider_failed"
    ]
    assert warning["level"] == "warning"
    assert (
        warning["document_id"],
        warning["error_code"],
        warning["error_message"],
        warning["transient"],
    ) == (str(document.id), "ai_unavailable", _BUSY, True)
    assert "exception" not in warning


def test_a_rejected_analysis_falls_back_to_the_heuristic_one_and_logs_why(
    db_session: Session,
    runner: _Runner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    rejected = "The AI provider rejected the request: HTTP 400 (invalid_request_error)."
    llm = _FakeLLM(ProviderRequestError(rejected, code="ai_rejected"))

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    assert llm.calls == 1
    db_session.refresh(document)
    assert (document.status, document.analysis_model, document.title) == (
        "ready",
        MOCK_ANALYSIS_MODEL,
        "Sorting algorithms",
    )
    [warning] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "document_analysis_fell_back"
    ]
    assert warning["level"] == "warning"
    assert (warning["document_id"], warning["error_code"], warning["error_message"]) == (
        str(document.id),
        "ai_rejected",
        rejected,
    )
    assert "exception" not in warning


def test_an_analysis_saved_by_an_earlier_attempt_with_the_same_model_is_reused(
    db_session: Session, runner: _Runner
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    analysis = DocumentAnalysis(
        title="Sorting, step by step",
        summary="How merge sort and quick sort put a list in order.",
        topics=["Merge sort", "Quick sort"],
        difficulty="hard",
    )
    llm = _FakeLLM(analysis=analysis)
    embedder = _FakeEmbedder(ProviderUnavailableError("The AI provider could not be reached."))

    first = runner.run(document.id, llm=llm, embedder=embedder)
    second = runner.run(document.id, llm=llm, embedder=embedder)

    assert first == PipelineOutcome.retry("ai_unavailable", None)
    assert second == PipelineOutcome.ready(chunk_count=3)
    assert llm.calls == 1
    db_session.refresh(document)
    assert (
        document.title,
        document.summary,
        document.topics,
        document.difficulty,
        document.analysis_model,
        document.attempts,
    ) == (
        "Sorting, step by step",
        "How merge sort and quick sort put a list in order.",
        ["Merge sort", "Quick sort"],
        "hard",
        _FAKE_CHAT_MODEL,
        2,
    )


def test_an_analysis_saved_by_another_model_is_made_again(
    db_session: Session, runner: _Runner
) -> None:
    # An earlier attempt fell back to the heuristic analysis.
    document = runner.store(
        _MARKDOWN.encode(),
        "sorting.md",
        title="An older title",
        summary="An older summary.",
        topics=["Older topic"],
        difficulty="easy",
        analysis_model=MOCK_ANALYSIS_MODEL,
    )
    llm = _FakeLLM()

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    assert llm.calls == 1
    db_session.refresh(document)
    assert (document.title, document.analysis_model) == ("Sorting algorithms", _FAKE_CHAT_MODEL)


def test_a_rejected_embedding_fails_the_document_with_its_code(
    db_session: Session, runner: _Runner
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    wrong_size = "The embedding model returned vectors of 768 numbers instead of 1536."
    embedder = _FakeEmbedder(ProviderRequestError(wrong_size, code="embedding_dimension_mismatch"))

    outcome = runner.run(document.id, embedder=embedder)

    assert outcome == PipelineOutcome.failed("embedding_dimension_mismatch")
    db_session.refresh(document)
    assert (document.status, document.error_code, document.error_message) == (
        "failed",
        "embedding_dimension_mismatch",
        wrong_size,
    )
    # The analysis is kept for the next attempt to reuse.
    assert document.analysis_model == MOCK_ANALYSIS_MODEL
    assert document.chunk_count is None
    assert _chunks(db_session, document.id) == []


def test_the_analysis_is_stored_normalised_with_a_blank_title_and_summary_as_none(
    db_session: Session, runner: _Runner
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    analysis = DocumentAnalysis(
        title=" \n\t ",
        summary="",
        topics=["  merge   sort ", "Merge Sort", "Quick sort", "\N{ZERO WIDTH SPACE}"],
        difficulty="easy",
    )

    outcome = runner.run(document.id, llm=_FakeLLM(analysis=analysis))

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    db_session.refresh(document)
    assert (document.title, document.summary, document.topics, document.difficulty) == (
        None,
        None,
        ["merge sort", "Quick sort"],
        "easy",
    )
    assert document.estimated_study_minutes == estimated_study_minutes(
        word_count(_MARKDOWN), "easy"
    )


def test_a_first_heading_of_5000_characters_gives_a_title_that_fits_its_column(
    db_session: Session, runner: _Runner
) -> None:
    heading = ("Normalisation " * 400)[:5000].strip()
    markdown = f"# {heading}\n\nThe first normal form keeps a single value in every cell."
    document = runner.store(markdown.encode(), "normal-forms.md")

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.ready(chunk_count=1)
    db_session.refresh(document)
    assert document.title is not None
    assert len(document.title) <= TITLE_MAX_LENGTH
    assert document.title.startswith("Normalisation Normalisation")
    [chunk] = _chunks(db_session, document.id)
    assert chunk.heading is not None
    assert len(chunk.heading) <= CHUNK_HEADING_MAX_LENGTH


def test_each_step_forward_clears_an_error_written_on_the_document_during_the_run(
    db_session: Session, runner: _Runner
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    while_embedding: list[tuple[str, str | None, str | None]] = []

    def write_an_error() -> None:
        # Written while the run works, without moving its run token.
        db_session.execute(
            update(Document)
            .where(Document.id == document.id)
            .values(error_code="queue_unavailable", error_message="Not queued.")
            .execution_options(synchronize_session=False)
        )
        db_session.commit()

    def note_the_state() -> None:
        db_session.refresh(document)
        while_embedding.append((document.status, document.error_code, document.error_message))
        write_an_error()

    llm = _FakeLLM(before_call=write_an_error)
    embedder = _FakeEmbedder(before_call=note_the_state)

    outcome = runner.run(document.id, llm=llm, embedder=embedder)

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    assert while_embedding == [("indexing", None, None)]
    db_session.refresh(document)
    assert (document.status, document.error_code, document.error_message) == ("ready", None, None)


def test_a_run_whose_document_a_newer_run_claimed_is_skipped_and_stores_no_chunks(
    db_session: Session, runner: _Runner
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    embedder = _FakeEmbedder(before_call=_claim_again(db_session, document))

    outcome = runner.run(document.id, embedder=embedder)

    assert outcome == PipelineOutcome.skipped("superseded")
    db_session.refresh(document)
    assert (document.status, document.attempts, document.chunk_count, document.processed_at) == (
        "indexing",
        2,
        None,
        None,
    )
    assert _chunks(db_session, document.id) == []


@pytest.mark.parametrize(
    ("stage", "batches"), [("analysis", []), ("embeddings", [3])], ids=["analysis", "embeddings"]
)
def test_a_document_deleted_during_the_run_is_skipped(
    db_session: Session, runner: _Runner, stage: str, batches: list[int]
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    delete_document = _delete(db_session, document)
    llm = _FakeLLM(before_call=delete_document if stage == "analysis" else _nothing)
    embedder = _FakeEmbedder(before_call=delete_document if stage == "embeddings" else _nothing)

    outcome = runner.run(document.id, llm=llm, embedder=embedder)

    assert outcome == PipelineOutcome.skipped("superseded")
    # The run stops at its next write: a document deleted during its analysis is never
    # embedded, which would be paid for.
    assert embedder.batches == batches
    assert not DocumentRepository(db_session).exists(document.id)
    assert _chunks(db_session, document.id) == []


@pytest.mark.parametrize(
    "error",
    [ProviderRequestError("Rejected.", code="ai_rejected"), ProviderUnavailableError(_BUSY)],
    ids=["failure", "retry"],
)
def test_a_run_that_lost_its_document_writes_no_error_on_it(
    db_session: Session, runner: _Runner, error: BaseException
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    embedder = _FakeEmbedder(error, before_call=_claim_again(db_session, document))

    outcome = runner.run(document.id, embedder=embedder)

    assert outcome == PipelineOutcome.skipped("superseded")
    db_session.refresh(document)
    assert (document.status, document.error_code, document.attempts) == ("indexing", None, 2)


def test_a_second_run_replaces_the_chunks_of_the_first(
    db_session: Session, runner: _Runner, integration_settings: Settings
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    assert runner.run(document.id) == PipelineOutcome.ready(chunk_count=3)
    first_ids = {chunk.id for chunk in _chunks(db_session, document.id)}
    # Sent through processing again, this time cut into smaller chunks.
    db_session.execute(
        update(Document)
        .where(Document.id == document.id)
        .values(status="uploaded")
        .execution_options(synchronize_session=False)
    )
    db_session.commit()
    integration_settings.chunk_size_chars = 40
    integration_settings.chunk_overlap_chars = 0

    outcome = runner.run(document.id)

    chunks = _chunks(db_session, document.id)
    assert outcome == PipelineOutcome.ready(chunk_count=len(chunks))
    assert len(chunks) > 3
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert first_ids.isdisjoint(chunk.id for chunk in chunks)
    db_session.refresh(document)
    assert (document.status, document.chunk_count, document.attempts) == ("ready", len(chunks), 2)


def test_each_step_is_a_transaction_and_the_last_locks_the_document_before_its_chunks(
    db_connection: Connection, runner: _Runner
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    statements: list[str] = []

    def record(**event_args: Any) -> None:
        if match := _RECORDED_STATEMENT.match(event_args["statement"]):
            statements.append(match.group())

    event.listen(db_connection, "before_cursor_execute", record, named=True)
    outcome = runner.run(document.id)
    event.remove(db_connection, "before_cursor_execute", record)

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    # A delete of the document locks its row before its chunks, through the cascade; the
    # opposite order in the last step could deadlock with it.
    assert statements == [
        "SAVEPOINT",
        "UPDATE documents",
        "RELEASE SAVEPOINT",
        "SAVEPOINT",
        "UPDATE documents",
        "RELEASE SAVEPOINT",
        "SAVEPOINT",
        "UPDATE documents",
        "DELETE FROM document_chunks",
        "INSERT INTO document_chunks",
        "RELEASE SAVEPOINT",
    ]


def test_no_transaction_is_open_while_the_file_is_read_or_a_provider_works(
    db_connection: Connection, runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    assert not db_connection.in_nested_transaction()
    open_during: dict[str, bool] = {}

    def note(step: str) -> Callable[[], None]:
        def check() -> None:
            open_during[step] = db_connection.in_nested_transaction()

        return check

    def checked_extract(*args: Any, **kwargs: Any) -> ExtractedDocument:
        note("reading")()
        return extract(*args, **kwargs)

    monkeypatch.setattr("app.documents.pipeline.extract", checked_extract)
    llm = _FakeLLM(before_call=note("analysing"))
    embedder = _FakeEmbedder(before_call=note("embedding"))

    outcome = runner.run(document.id, llm=llm, embedder=embedder)

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    assert open_during == {"reading": False, "analysing": False, "embedding": False}


def test_a_run_that_reaches_its_deadline_between_embedding_batches_fails_as_a_timeout(
    db_session: Session,
    runner: _Runner,
    integration_settings: Settings,
    clock: _FakeClock,
) -> None:
    integration_settings.embedding_batch_size = 1
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    embedder = _FakeEmbedder(before_call=lambda: clock.advance(timedelta(minutes=10)))

    outcome = runner.run(document.id, embedder=embedder)

    assert outcome == PipelineOutcome.failed("processing_timeout")
    assert embedder.batches == [1]
    db_session.refresh(document)
    assert (document.status, document.error_code, document.updated_at) == (
        "failed",
        "processing_timeout",
        _START + timedelta(minutes=10),
    )
    assert _chunks(db_session, document.id) == []


@pytest.mark.parametrize(
    ("spent", "expected"),
    [
        (_RUN_TIME_LIMIT - timedelta(microseconds=1), PipelineOutcome.ready(chunk_count=3)),
        (_RUN_TIME_LIMIT, PipelineOutcome.failed("processing_timeout")),
    ],
    ids=["just-before", "at-the-deadline"],
)
def test_the_deadline_falls_a_margin_before_the_soft_time_limit(
    runner: _Runner, spent: timedelta, expected: PipelineOutcome
) -> None:
    runner.settings.embedding_batch_size = 1
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    # The first batch takes this long; the deadline is checked before each of the others.
    embedder = _FakeEmbedder(before_call=lambda: runner.clock.move_to(_START + spent))

    outcome = runner.run(document.id, embedder=embedder)

    assert outcome == expected


def test_a_run_that_reaches_its_deadline_while_reading_a_pdf_fails_as_a_timeout(
    runner: _Runner, clock: _FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = runner.store(_LECTURE_PDF.read_bytes(), "lecture-ru.pdf")
    stopped_reading: list[bool] = []

    def slow_start(*args: Any, **kwargs: Any) -> ExtractedDocument:
        clock.advance(_RUN_TIME_LIMIT)
        try:
            return extract(*args, **kwargs)
        except ProcessingDeadlineExceeded:
            stopped_reading.append(True)
            raise

    monkeypatch.setattr("app.documents.pipeline.extract", slow_start)
    llm = _FakeLLM()

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.failed("processing_timeout")
    # The reading itself stops, rather than going through every page first.
    assert stopped_reading == [True]
    assert llm.calls == 0


def test_a_run_whose_reading_took_it_to_its_deadline_asks_for_no_analysis(
    db_session: Session, runner: _Runner, clock: _FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Markdown is read in one go, with no deadline check of its own.
    document = runner.store(_MARKDOWN.encode(), "sorting.md")

    def slow_read(*args: Any, **kwargs: Any) -> ExtractedDocument:
        extracted = extract(*args, **kwargs)
        clock.advance(_RUN_TIME_LIMIT)
        return extracted

    monkeypatch.setattr("app.documents.pipeline.extract", slow_read)
    llm = _FakeLLM()

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.failed("processing_timeout")
    assert llm.calls == 0
    db_session.refresh(document)
    assert (document.status, document.analysis_model) == ("failed", None)


def test_a_run_whose_analysis_took_it_to_its_deadline_embeds_nothing(
    db_session: Session, runner: _Runner, clock: _FakeClock
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    llm = _FakeLLM(before_call=lambda: clock.advance(_RUN_TIME_LIMIT))
    embedder = _FakeEmbedder()

    outcome = runner.run(document.id, llm=llm, embedder=embedder)

    assert outcome == PipelineOutcome.failed("processing_timeout")
    assert embedder.batches == []
    db_session.refresh(document)
    # The analysis is kept for the next attempt to reuse.
    assert (document.status, document.analysis_model) == ("failed", _FAKE_CHAT_MODEL)


def _leave_after_the_claim(
    monkeypatch: pytest.MonkeyPatch, clock: _FakeClock, left: timedelta
) -> None:
    """Move the clock to left before the deadline as soon as a run claims its document."""
    claim = DocumentRepository.claim_for_processing

    def claim_then_wait(
        repository: DocumentRepository, document_id: uuid.UUID, now: datetime
    ) -> ClaimedDocument | None:
        claimed = claim(repository, document_id, now)
        clock.advance(_RUN_TIME_LIMIT - left)
        return claimed

    monkeypatch.setattr(DocumentRepository, "claim_for_processing", claim_then_wait)


@_NEEDS_ALARM
def test_a_damaged_pdf_that_keeps_the_pdf_library_busy_stops_at_the_deadline(
    db_session: Session, runner: _Runner, clock: _FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # While pypdf repairs a damaged file it checks no deadline and swallows every Exception,
    # Celery's soft time limit included.
    document = runner.store(slow_to_repair_pdf(_SLOW_TO_REPAIR_PDF_BYTES), "damaged.pdf")
    _leave_after_the_claim(monkeypatch, clock, timedelta(seconds=1))
    handler = signal.getsignal(signal.SIGALRM)

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.failed("processing_timeout")
    db_session.refresh(document)
    assert (document.status, document.error_code) == ("failed", "processing_timeout")
    # The alarm is off and the signal is handled as before.
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    assert signal.getsignal(signal.SIGALRM) == handler


@_NEEDS_ALARM
def test_the_deadline_alarm_is_off_once_the_file_is_read(
    runner: _Runner, clock: _FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Left on, it would go off in the middle of a later step.
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    _leave_after_the_claim(monkeypatch, clock, timedelta(seconds=1))
    handler = signal.getsignal(signal.SIGALRM)
    alarms: list[tuple[float, float]] = []
    llm = _FakeLLM(before_call=lambda: alarms.append(signal.getitimer(signal.ITIMER_REAL)))

    outcome = runner.run(document.id, llm=llm)

    assert outcome == PipelineOutcome.ready(chunk_count=3)
    assert alarms == [(0.0, 0.0)]
    assert signal.getsignal(signal.SIGALRM) == handler


def test_a_run_outside_the_main_thread_goes_on_without_the_deadline_alarm(
    runner: _Runner,
) -> None:
    # Only the main thread may set a signal handler. Were the alarm set anyway, a worker
    # running tasks in threads would fail every document.
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    outcomes: list[PipelineOutcome] = []
    thread = threading.Thread(target=lambda: outcomes.append(runner.run(document.id)))

    thread.start()
    thread.join()

    assert outcomes == [PipelineOutcome.ready(chunk_count=3)]


@pytest.mark.parametrize(
    "left", [timedelta(0), timedelta(seconds=-1)], ids=["at-the-deadline", "past-it"]
)
def test_a_run_out_of_time_before_its_pdf_is_read_never_opens_it(
    runner: _Runner, clock: _FakeClock, monkeypatch: pytest.MonkeyPatch, left: timedelta
) -> None:
    # An alarm can only be set for some time to come: one for no time would never go off.
    document = runner.store(slow_to_repair_pdf(_SLOW_TO_REPAIR_PDF_BYTES), "damaged.pdf")
    _leave_after_the_claim(monkeypatch, clock, left)

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.failed("processing_timeout")


@pytest.mark.parametrize("stage", ["analysis", "embeddings"])
def test_the_soft_time_limit_in_any_stage_fails_the_document_as_a_timeout(
    db_session: Session, runner: _Runner, stage: str
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    llm, embedder = _providers(stage, SoftTimeLimitExceeded())

    outcome = runner.run(document.id, llm=llm, embedder=embedder)

    assert outcome == PipelineOutcome.failed("processing_timeout")
    db_session.refresh(document)
    assert (document.status, document.error_code) == ("failed", "processing_timeout")
    assert document.error_message


def test_the_soft_time_limit_while_the_chunks_are_stored_undoes_the_last_step(
    db_session: Session,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = runner.store(_MARKDOWN.encode(), "sorting.md")

    def out_of_time(*_: object) -> None:
        raise SoftTimeLimitExceeded

    monkeypatch.setattr(DocumentChunkRepository, "replace_for_document", out_of_time)

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.failed("processing_timeout")
    db_session.refresh(document)
    # The document was marked ready in the same transaction, and is no longer.
    assert (
        document.status,
        document.error_code,
        document.chunk_count,
        document.processed_at,
    ) == ("failed", "processing_timeout", None, None)


def test_an_unexpected_error_fails_the_document_as_an_internal_error_and_is_logged(
    db_session: Session,
    runner: _Runner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    embedder = _FakeEmbedder(RuntimeError("x" * 5000))

    outcome = runner.run(document.id, embedder=embedder)

    assert outcome == PipelineOutcome.failed("internal_error")
    db_session.refresh(document)
    assert (document.status, document.error_code) == ("failed", "internal_error")
    assert document.error_message is not None
    assert len(document.error_message) <= ERROR_MESSAGE_MAX_LENGTH
    assert "RuntimeError" in document.error_message
    assert "xxx" not in document.error_message
    [line] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "document_processing_crashed"
    ]
    assert line["level"] == "error"
    assert line["document_id"] == str(document.id)
    assert line["exception"][0]["exc_type"] == "RuntimeError"


def test_chunks_the_database_rejects_fail_the_document_as_an_internal_error(
    db_session: Session,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    document = runner.store(_MARKDOWN.encode(), "sorting.md")

    def chunks_with_a_repeated_index(text: str, *, size: int, overlap: int) -> list[Chunk]:
        first = chunk_markdown(text, size=size, overlap=overlap)[0]
        return [first, first]

    monkeypatch.setattr("app.documents.pipeline.chunk_markdown", chunks_with_a_repeated_index)

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.failed("internal_error")
    db_session.refresh(document)
    assert (document.status, document.error_code, document.chunk_count) == (
        "failed",
        "internal_error",
        None,
    )
    assert document.error_message is not None
    assert "IntegrityError" in document.error_message
    assert _chunks(db_session, document.id) == []
    [line] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "document_processing_crashed"
    ]
    # Logged by its codes alone: the rejected statement's values hold the document's text.
    assert "Sorting puts the items" not in json.dumps(line)
    assert (line["exc_type"], line["sqlstate"], line["constraint"]) == (
        "IntegrityError",
        "23505",
        "uq_document_chunks_document_id_chunk_index",
    )


def test_a_row_the_database_refuses_is_not_quoted_in_the_log(
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    document = runner.store(_MARKDOWN.encode(), "sorting.md")
    # Stands for any bug that stores a value a CHECK refuses. PostgreSQL's error then quotes
    # the refused row, with the file name and the analysis.
    monkeypatch.setattr("app.documents.pipeline.estimated_study_minutes", lambda *_: -1)

    outcome = runner.run(document.id)

    assert outcome == PipelineOutcome.failed("internal_error")
    [line] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "document_processing_crashed"
    ]
    # The file name, the title, the summary and the topics all speak of sorting.
    assert "sort" not in json.dumps(line).lower()
    assert (line["exc_type"], line["sqlstate"], line["constraint"]) == (
        "IntegrityError",
        "23514",
        "ck_documents_counts_non_negative",
    )
