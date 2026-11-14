import hashlib
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import httpx2
import pytest
from openai import OpenAI
from sqlalchemy import Delete, Update, delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.documents.queue import QueueUnavailableError
from app.documents.storage import FileStorage
from app.llm.base import (
    EMBEDDING_DIMENSIONS,
    AnalysisRequest,
    AnalysisResult,
    EmbeddingProvider,
    ProviderUnavailableError,
)
from app.llm.mock_provider import (
    MOCK_ANALYSIS_MODEL,
    MOCK_EMBEDDING_MODEL,
    HashingEmbeddingProvider,
    MockLLMProvider,
)
from app.llm.openai_provider import OpenAIEmbeddingProvider
from app.llm.probe import PROBE_SENTENCE, UNSENDABLE_KEY_MESSAGE
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace
from app.reindex import CAVEATS, main
from app.repositories.document_chunks import ChunkRow, DocumentChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.workers.celery_app import PROCESS_DOCUMENT_TASK_NAME, celery_app
from app.workers.tasks import PipelineDependencies, process_document

pytestmark = pytest.mark.integration

_NOW: Final = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
_LATER: Final = _NOW + timedelta(hours=1)
_INDEXED_AT: Final = _NOW - timedelta(days=30)
# The models of a live configuration, before the switch to the built-in models that the test
# settings select.
_OLDER_EMBEDDING_MODEL: Final = "text-embedding-3-small"
_OLDER_CHAT_MODEL: Final = "gpt-5.4-mini"
# Invented, and as long as a real key.
_API_KEY: Final = "embedding-key-for-reindex-tests-".ljust(40, "0")
_SAVED_TITLE: Final = "Notes on photosynthesis"
_NOTES: Final = """# Photosynthesis

Plants turn light, water and carbon dioxide into sugar and oxygen.

## Light reactions

Chlorophyll absorbs light, and its energy splits water into oxygen and hydrogen."""
# A ready document was analysed by the built-in chat model and embedded by the older model.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {
        "title": _SAVED_TITLE,
        "summary": "How plants turn light into sugar.",
        "topics": ["Light reactions"],
        "difficulty": "easy",
        "analysis_model": MOCK_ANALYSIS_MODEL,
        "chunk_count": 1,
        "embedding_model": _OLDER_EMBEDDING_MODEL,
        "processed_at": _INDEXED_AT,
    },
    "failed": {"error_code": "pdf_unreadable"},
}
# How a document can change between the listing and its compare-and-set: another run queues
# it again, a worker re-indexes it, or its owner deletes it.
_CHANGES: Final[dict[str, Callable[[uuid.UUID], Update | Delete]]] = {
    "queued-again": lambda document_id: (
        update(Document).where(Document.id == document_id).values(status="uploaded")
    ),
    "re-indexed": lambda document_id: (
        update(Document)
        .where(Document.id == document_id)
        .values(embedding_model=MOCK_EMBEDDING_MODEL)
    ),
    "deleted": lambda document_id: delete(Document).where(Document.id == document_id),
}


@dataclass(frozen=True, slots=True)
class _SavedAnalysis:
    """The chat model that analysed a document, and what processing it again does with that."""

    model: str
    # The requests the chat model gets, and the title the document ends with.
    requests: int
    title: str


_SAVED_ANALYSES: Final = {
    "same-chat-model": _SavedAnalysis(MOCK_ANALYSIS_MODEL, requests=0, title=_SAVED_TITLE),
    "another-chat-model": _SavedAnalysis(_OLDER_CHAT_MODEL, requests=1, title="Photosynthesis"),
}


def _nothing(document_id: uuid.UUID) -> None:
    return None


class _Queue:
    """Stands in for the broker: records each document, or refuses it like a broker that is down.

    before_enqueue runs first, while the command waits for the broker.
    """

    def __init__(
        self, *, unavailable: bool = False, before_enqueue: Callable[[uuid.UUID], None] = _nothing
    ) -> None:
        self.enqueued: list[uuid.UUID] = []
        self._unavailable = unavailable
        self._before_enqueue = before_enqueue

    def enqueue(self, document_id: uuid.UUID) -> None:
        self._before_enqueue(document_id)
        if self._unavailable:
            raise QueueUnavailableError("The message broker did not accept the request.")
        self.enqueued.append(document_id)


class _UnavailableEmbedder:
    """An embedding model that cannot be reached; records what it was asked to embed."""

    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    @property
    def model_name(self) -> str:
        return "text-embedding-3-large"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.requests.append(list(texts))
        raise ProviderUnavailableError("The AI provider could not be reached.")


class _CountingLLM:
    """The built-in analysis, counting the documents it is asked to analyse."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def model_name(self) -> str:
        return MOCK_ANALYSIS_MODEL

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult:
        self.calls += 1
        return MockLLMProvider().analyze_document(request)


@dataclass
class _Library:
    """Stores committed documents, each of a new owner and with its file."""

    session: Session
    storage: FileStorage

    def store(self, status: DocumentStatus = "ready", **values: object) -> Document:
        owner = UserRepository(self.session).add(
            User(
                email=f"{uuid.uuid4().hex}@example.com",
                password_hash="hash",
                display_name="Owner",
            )
        )
        workspace = WorkspaceRepository(self.session).add(
            Workspace(owner_id=owner.id, name="Biology")
        )
        document_id = uuid.uuid4()
        key = self.storage.key_for(workspace.id, document_id, ".md")
        path = self.storage.path_for(key)
        content = _NOTES.encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        fields: dict[str, object] = {
            "id": document_id,
            "workspace_id": workspace.id,
            "original_filename": "photosynthesis.md",
            "content_type": "text/markdown",
            "size_bytes": len(content),
            "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
            "storage_key": key,
            "status": status,
            "attempts": 1,
            "created_at": _INDEXED_AT,
            "updated_at": _INDEXED_AT,
            **_STATUS_FIELDS.get(status, {}),
        }
        fields.update(values)
        document = DocumentRepository(self.session).add(Document(**fields))
        self.session.commit()
        return document


@dataclass
class _Command:
    """Runs the command on the test database, at a fixed time and never with the real broker."""

    settings: Settings
    session_factory: sessionmaker[Session]

    def run(
        self,
        *args: str,
        queue: _Queue,
        embedder: EmbeddingProvider | None = None,
        now: datetime = _NOW,
    ) -> int:
        return main(
            list(args),
            settings=self.settings,
            embedder=embedder,
            queue=queue,
            session_factory=self.session_factory,
            clock=lambda: now,
        )


@pytest.fixture
def storage(integration_settings: Settings) -> FileStorage:
    return FileStorage(integration_settings.storage_dir)


@pytest.fixture
def library(db_session: Session, storage: FileStorage) -> _Library:
    return _Library(db_session, storage)


@pytest.fixture
def command(integration_settings: Settings, session_factory: sessionmaker[Session]) -> _Command:
    return _Command(integration_settings, session_factory)


@pytest.fixture
def worker_llm(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    integration_settings: Settings,
) -> _CountingLLM:
    """The chat model of the worker's task, which runs on the test's database, files and clock."""
    llm = _CountingLLM()
    dependencies = PipelineDependencies(
        session_factory=session_factory,
        storage=storage,
        llm=llm,
        embedder=HashingEmbeddingProvider(),
        settings=integration_settings,
        clock=lambda: _LATER,
    )
    monkeypatch.setattr("app.workers.tasks.get_settings", lambda: integration_settings)
    monkeypatch.setattr(
        "app.workers.tasks.build_pipeline_dependencies", lambda _settings: dependencies
    )
    return llm


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def _one_hot(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


def _refuse_connection(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("Connection refused", request=request)


def test_only_ready_documents_of_another_embedding_model_are_queued_again(
    db_session: Session, library: _Library, command: _Command, capsys: pytest.CaptureFixture[str]
) -> None:
    first = library.store(created_at=_INDEXED_AT - timedelta(days=1))
    second = library.store()
    current = library.store(embedding_model=MOCK_EMBEDDING_MODEL)
    statuses: tuple[DocumentStatus, ...] = ("uploaded", "processing", "indexing", "failed")
    busy = [library.store(status, embedding_model=_OLDER_EMBEDDING_MODEL) for status in statuses]
    queue = _Queue()

    assert command.run(queue=queue) == 0

    assert queue.enqueued == [first.id, second.id]
    for document in (first, second):
        db_session.refresh(document)
        assert (document.status, document.error_code, document.updated_at, document.attempts) == (
            "uploaded",
            None,
            _NOW,
            1,
        )
    for document, status in zip((current, *busy), ("ready", *statuses), strict=True):
        db_session.refresh(document)
        assert (document.status, document.updated_at) == (status, _INDEXED_AT)
    lines = _lines(capsys)
    assert "The embedding model mock-hashing-v1 answered the probe." in lines
    assert "Documents that will be re-indexed: 2" in lines
    assert "Re-indexed (queued): 2" in lines
    assert "Skipped because they changed meanwhile: 0" in lines
    assert "Failed to queue: 0" in lines


def test_a_dry_run_counts_the_documents_to_re_index_and_re_analyse_and_changes_nothing(
    db_session: Session, library: _Library, command: _Command, capsys: pytest.CaptureFixture[str]
) -> None:
    documents = [
        # Analysed by the current chat model: the analysis is used again.
        library.store(),
        library.store(analysis_model=_OLDER_CHAT_MODEL),
        library.store(difficulty=None),
    ]
    queue = _Queue()

    assert command.run("--dry-run", queue=queue) == 0

    assert queue.enqueued == []
    for document in documents:
        db_session.refresh(document)
        assert (document.status, document.updated_at) == ("ready", _INDEXED_AT)
    lines = _lines(capsys)
    assert "Documents that would be re-indexed: 3" in lines
    assert "Documents that would be re-analysed too: 2" in lines
    assert lines[-1] == "Dry run: nothing was changed."
    assert not any(line.startswith("Re-indexed") for line in lines)


def test_the_count_of_re_analysed_documents_says_what_a_re_analysis_costs(
    library: _Library, command: _Command, capsys: pytest.CaptureFixture[str]
) -> None:
    library.store(analysis_model=_OLDER_CHAT_MODEL)

    assert command.run("--dry-run", queue=_Queue()) == 0

    output = capsys.readouterr().out
    assert "another chat model than mock-heuristic-v1 analysed it" in output
    assert "its analysis is incomplete" in output
    assert "each re-analysis is a paid request" in output


def test_a_second_run_finds_nothing_left_to_queue(
    db_session: Session, library: _Library, command: _Command, capsys: pytest.CaptureFixture[str]
) -> None:
    document = library.store()
    queue = _Queue()
    assert command.run(queue=queue) == 0
    capsys.readouterr()

    assert command.run(queue=queue, now=_LATER) == 0

    assert queue.enqueued == [document.id]
    db_session.refresh(document)
    assert (document.status, document.updated_at) == ("uploaded", _NOW)
    assert _lines(capsys) == [
        "The embedding model mock-hashing-v1 answered the probe.",
        "Nothing to re-index: every ready document was embedded by mock-hashing-v1.",
    ]


def test_each_document_is_committed_before_it_is_published(
    library: _Library, command: _Command, session_factory: sessionmaker[Session]
) -> None:
    document = library.store()
    claims: list[uuid.UUID | None] = []

    def claim_at_once(document_id: uuid.UUID) -> None:
        # A worker may claim the document the moment it is published, in a session of its
        # own: the session factory fails the test if the command's session is still open.
        with session_factory.begin() as session:
            claimed = DocumentRepository(session).claim_for_processing(document_id, _NOW)
        claims.append(None if claimed is None else claimed.id)

    assert command.run(queue=_Queue(before_enqueue=claim_at_once)) == 0

    assert claims == [document.id]


@pytest.mark.parametrize("change", _CHANGES.values(), ids=_CHANGES.keys())
def test_a_document_that_changed_after_it_was_listed_is_skipped(
    db_session: Session,
    library: _Library,
    command: _Command,
    capsys: pytest.CaptureFixture[str],
    change: Callable[[uuid.UUID], Update | Delete],
) -> None:
    first = library.store(created_at=_INDEXED_AT - timedelta(days=1))
    second = library.store(analysis_model=_OLDER_CHAT_MODEL)

    def change_the_second(document_id: uuid.UUID) -> None:
        if document_id == first.id:
            db_session.execute(change(second.id).execution_options(synchronize_session=False))
            db_session.commit()

    queue = _Queue(before_enqueue=change_the_second)

    assert command.run(queue=queue) == 0

    assert queue.enqueued == [first.id]
    changed = DocumentRepository(db_session).reload(second.id)
    # Left as the change made it: the command's own write would have set its time.
    assert changed is None or changed.updated_at == _INDEXED_AT
    lines = _lines(capsys)
    assert "Documents that will be re-analysed too: 1" in lines
    assert "Re-indexed (queued): 1" in lines
    # Only the queued documents count: the skipped one would have been re-analysed.
    assert "Of them re-analysed: 0" in lines
    assert "Skipped because they changed meanwhile: 1" in lines
    assert "Failed to queue: 0" in lines


@pytest.mark.parametrize("args", [[], ["--dry-run"]], ids=["run", "dry-run"])
def test_an_embedding_model_that_fails_the_probe_stops_the_command_before_any_change(
    db_session: Session,
    library: _Library,
    command: _Command,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    document = library.store()
    embedder = _UnavailableEmbedder()
    queue = _Queue()

    assert command.run(*args, queue=queue, embedder=embedder) == 1

    assert embedder.requests == [[PROBE_SENTENCE]]
    assert queue.enqueued == []
    db_session.refresh(document)
    assert (document.status, document.updated_at) == ("ready", _INDEXED_AT)
    assert _lines(capsys)[-2:] == [
        "The embedding model text-embedding-3-large failed the probe: ai_unavailable"
        " (The AI provider could not be reached.)",
        "Nothing was changed.",
    ]


def test_an_embedding_key_that_cannot_be_sent_stops_the_command_before_any_change(
    db_session: Session, library: _Library, command: _Command, capsys: pytest.CaptureFixture[str]
) -> None:
    document = library.store()
    queue = _Queue()
    # Pasted with a no-break space, the key cannot go into a header; a request would be refused.
    with OpenAI(
        api_key=f"{_API_KEY}\N{NO-BREAK SPACE}",
        base_url="http://llm.test/v1",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(_refuse_connection)),
    ) as client:
        embedder = OpenAIEmbeddingProvider(client=client, model="text-embedding-3-large")

        assert command.run(queue=queue, embedder=embedder) == 1

    assert queue.enqueued == []
    db_session.refresh(document)
    assert (document.status, document.updated_at) == ("ready", _INDEXED_AT)
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-2:] == [
        f"The embedding model text-embedding-3-large failed the probe: {UNSENDABLE_KEY_MESSAGE}",
        "Nothing was changed.",
    ]
    assert _API_KEY not in captured.out
    assert _API_KEY not in captured.err


def test_a_document_the_queue_does_not_take_is_failed_and_the_run_stops_there(
    db_session: Session, library: _Library, command: _Command, capsys: pytest.CaptureFixture[str]
) -> None:
    first = library.store(created_at=_INDEXED_AT - timedelta(days=1))
    second = library.store()

    assert command.run(queue=_Queue(unavailable=True)) == 1

    db_session.refresh(first)
    assert (
        first.status,
        first.error_code,
        first.error_message,
        first.updated_at,
        first.attempts,
    ) == (
        "failed",
        "queue_unavailable",
        "The document could not be queued for re-indexing.",
        _NOW,
        1,
    )
    # Its owner's Retry sends it for processing again.
    assert DocumentRepository(db_session).mark_for_retry(first.id, first.workspace_id, _LATER)
    # A broker that is down would fail every document after it in the same way.
    db_session.refresh(second)
    assert (second.status, second.updated_at) == ("ready", _INDEXED_AT)
    lines = _lines(capsys)
    assert (
        f"The queue did not take document {first.id}: it shows failed (queue_unavailable)"
        " until its owner retries it." in lines
    )
    assert "Stopped there. Documents left as they were, for a later run: 1" in lines
    assert "Re-indexed (queued): 0" in lines
    assert "Failed to queue: 1" in lines


def test_a_failed_publish_whose_document_a_worker_claimed_all_the_same_leaves_it_alone(
    db_session: Session,
    library: _Library,
    command: _Command,
    session_factory: sessionmaker[Session],
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = library.store()

    def claim_at_once(document_id: uuid.UUID) -> None:
        # The broker took the message although the publish fails, and a worker claims it.
        with session_factory.begin() as session:
            DocumentRepository(session).claim_for_processing(document_id, _NOW)

    queue = _Queue(unavailable=True, before_enqueue=claim_at_once)

    assert command.run(queue=queue) == 1

    db_session.refresh(document)
    assert (document.status, document.error_code, document.attempts) == ("processing", None, 2)
    lines = _lines(capsys)
    assert (
        f"The queue reported an error for document {document.id}, which has moved on all the"
        " same: a worker claimed it, or its owner deleted it." in lines
    )
    assert "Failed to queue: 1" in lines


def test_a_run_ends_with_what_happens_meanwhile(
    library: _Library, command: _Command, capsys: pytest.CaptureFixture[str]
) -> None:
    library.store()

    assert command.run(queue=_Queue()) == 0

    assert _lines(capsys)[-len(CAVEATS) :] == list(CAVEATS)
    caveats = " ".join(CAVEATS)
    assert "does not wait for processing" in caveats
    assert "too_many_active_documents" in caveats
    assert "while an AI provider is unavailable shows failed" in caveats
    assert "caps do not apply to this command" in caveats


def test_without_a_queue_the_documents_are_published_with_the_workers_celery_app(
    library: _Library,
    integration_settings: Settings,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = library.store()
    published: list[tuple[str, list[str]]] = []

    def record(name: str, args: list[str], **options: object) -> None:
        published.append((name, args))

    # Never the real broker: the message stops at the worker's Celery app.
    monkeypatch.setattr(celery_app, "send_task", record)

    code = main(
        [], settings=integration_settings, session_factory=session_factory, clock=lambda: _NOW
    )

    assert code == 0
    assert published == [(PROCESS_DOCUMENT_TASK_NAME, [str(document.id)])]


@pytest.mark.parametrize("analysis", _SAVED_ANALYSES.values(), ids=_SAVED_ANALYSES.keys())
def test_a_queued_document_is_processed_into_chunks_of_the_current_model(
    library: _Library,
    command: _Command,
    worker_llm: _CountingLLM,
    capsys: pytest.CaptureFixture[str],
    analysis: _SavedAnalysis,
) -> None:
    session = library.session
    document = library.store(analysis_model=analysis.model)
    old_chunk = ChunkRow(
        chunk_index=0,
        content=_NOTES,
        heading=None,
        page_start=None,
        page_end=None,
        char_count=len(_NOTES),
        embedding=_one_hot(0),
    )
    DocumentChunkRepository(session).replace_for_document(
        document.id, document.workspace_id, [old_chunk]
    )
    session.commit()
    [old_chunk_id] = session.scalars(
        select(DocumentChunk.id).where(DocumentChunk.document_id == document.id)
    )
    queue = _Queue()
    assert command.run(queue=queue) == 0
    assert f"Of them re-analysed: {analysis.requests}" in _lines(capsys)

    [result] = [process_document.apply(args=(str(queued),)) for queued in queue.enqueued]

    assert result.successful(), result.traceback
    assert worker_llm.calls == analysis.requests
    session.refresh(document)
    assert (
        document.status,
        document.embedding_model,
        document.analysis_model,
        document.title,
        document.processed_at,
    ) == ("ready", MOCK_EMBEDDING_MODEL, MOCK_ANALYSIS_MODEL, analysis.title, _LATER)
    chunks, total = DocumentChunkRepository(session).list_for_document(
        document.id, offset=0, limit=10
    )
    assert document.chunk_count == total == 2
    assert old_chunk_id not in {chunk.id for chunk in chunks}
    assert chunks[0].content.startswith("Plants turn light")
    # Nothing is left for a later run.
    assert command.run(queue=queue, now=_LATER) == 0
    assert queue.enqueued == [document.id]
