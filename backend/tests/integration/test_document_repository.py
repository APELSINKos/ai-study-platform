import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app.models.document import ERROR_MESSAGE_MAX_LENGTH, Document, DocumentStatus
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.document_chunks import ChunkRow, DocumentChunkRepository
from app.repositories.documents import ClaimedDocument, DocumentRepository, OwnerUsage
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository

pytestmark = pytest.mark.integration

_NOW: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
_EARLIER: Final = _NOW - timedelta(minutes=5)
# The embedding model of a ready document below unless it names another, and the models of
# an earlier configuration.
_CURRENT_EMBEDDING_MODEL: Final = "mock-hashing-v1"
_OLDER_EMBEDDING_MODEL: Final = "text-embedding-3-small"
_CHAT_MODEL: Final = "gpt-5.4-mini"
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 2, "embedding_model": "mock-hashing-v1", "processed_at": _NOW},
    "failed": {"error_code": "pdf_unreadable"},
}
# Each write a processing run makes after its claim, made with a given run token.
_RUN_WRITES: Final[dict[str, Callable[[DocumentRepository, uuid.UUID, int], bool]]] = {
    "update_if_current": lambda repository, document_id, token: repository.update_if_current(
        document_id, token, _NOW, word_count=10
    ),
    "mark_failed": lambda repository, document_id, token: repository.mark_failed(
        document_id, token, "no_text", "The document has no text.", _NOW
    ),
    "mark_retry_pending": lambda repository, document_id, token: repository.mark_retry_pending(
        document_id, token, "ai_unavailable", "The AI provider is busy.", _NOW
    ),
    "complete": lambda repository, document_id, token: repository.complete(
        document_id, token, _NOW, chunk_count=1, embedding_model="mock-hashing-v1", processing_ms=1
    ),
}


def _user(session: Session, email: str = "owner@example.com") -> User:
    return UserRepository(session).add(
        User(email=email, password_hash="hash", display_name="Owner")
    )


def _workspace(session: Session, owner: User, name: str = "Algorithms") -> Workspace:
    return WorkspaceRepository(session).add(Workspace(owner_id=owner.id, name=name))


def _new_document(
    workspace: Workspace, status: DocumentStatus = "uploaded", **values: object
) -> Document:
    document_id = uuid.uuid4()
    fields: dict[str, object] = {
        "id": document_id,
        "workspace_id": workspace.id,
        "original_filename": "notes.md",
        "content_type": "text/markdown",
        "size_bytes": 1024,
        "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
        "storage_key": f"{workspace.id}/{document_id}.md",
        "status": status,
        **_STATUS_FIELDS.get(status, {}),
    }
    fields.update(values)
    return Document(**fields)


def _document(
    session: Session, workspace: Workspace, status: DocumentStatus = "uploaded", **values: object
) -> Document:
    return DocumentRepository(session).add(_new_document(workspace, status, **values))


def _embedding(hot: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[hot] = 1.0
    return vector


def _row(
    index: int,
    *,
    content: str | None = None,
    heading: str | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
) -> ChunkRow:
    text = f"Chunk number {index}" if content is None else content
    return ChunkRow(
        chunk_index=index,
        content=text,
        heading=heading,
        page_start=page_start,
        page_end=page_end,
        char_count=len(text),
        embedding=_embedding(index),
    )


def test_add_assigns_an_id_and_get_finds_the_document(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))

    document = repository.add(_new_document(workspace))

    assert repository.get(document.id) is document
    assert repository.get(uuid.uuid4()) is None


def test_get_for_owner_finds_only_the_owners_document(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    owner = _user(db_session)
    stranger = _user(db_session, "stranger@example.com")
    document = _document(db_session, _workspace(db_session, owner))

    assert repository.get_for_owner(document.id, owner.id) is document
    assert repository.get_for_owner(document.id, stranger.id) is None
    assert repository.get_for_owner(uuid.uuid4(), owner.id) is None


def test_get_by_sha256_looks_only_inside_the_workspace(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner, "Home")
    other = _workspace(db_session, owner, "Other")
    document = _document(db_session, workspace)

    assert repository.get_by_sha256(workspace.id, document.sha256) is document
    assert repository.get_by_sha256(other.id, document.sha256) is None
    assert repository.get_by_sha256(workspace.id, "0" * 64) is None


def test_list_for_workspace_puts_the_newest_first_and_breaks_ties_by_id(
    db_session: Session,
) -> None:
    repository = DocumentRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    _document(db_session, _workspace(db_session, owner, "Other"))
    oldest = _document(db_session, workspace, created_at=_NOW - timedelta(days=1))
    tied = [_document(db_session, workspace, created_at=_NOW) for _ in range(3)]

    documents, total = repository.list_for_workspace(workspace.id, status=None, offset=0, limit=10)

    tied_newest_first = sorted(tied, key=lambda document: document.id, reverse=True)
    assert documents == [*tied_newest_first, oldest]
    assert total == 4


def test_list_for_workspace_filters_by_status_and_counts_the_filtered_total(
    db_session: Session,
) -> None:
    repository = DocumentRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))
    failed = [
        _document(db_session, workspace, "failed", created_at=_NOW - timedelta(hours=hours))
        for hours in range(2)
    ]
    _document(db_session, workspace, "ready")
    _document(db_session, workspace, "uploaded")

    documents, total = repository.list_for_workspace(
        workspace.id, status="failed", offset=0, limit=10
    )

    assert documents == failed
    assert total == 2


def test_list_for_workspace_pages_through_the_documents(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))
    newest_first = [
        _document(db_session, workspace, created_at=_NOW - timedelta(minutes=minutes))
        for minutes in range(5)
    ]

    page, total = repository.list_for_workspace(workspace.id, status=None, offset=2, limit=2)
    beyond, beyond_total = repository.list_for_workspace(
        workspace.id, status=None, offset=10, limit=2
    )

    assert page == newest_first[2:4]
    assert total == 5
    assert beyond == []
    assert beyond_total == 5


def test_delete_removes_the_document_and_its_chunks(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    document = _document(db_session, _workspace(db_session, _user(db_session)))
    DocumentChunkRepository(db_session).replace_for_document(
        document.id, document.workspace_id, [_row(0), _row(1)]
    )
    document_id = document.id

    assert repository.delete(document) is True

    assert repository.get(document_id) is None
    remaining = db_session.scalars(
        select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
    ).all()
    assert remaining == []


def test_delete_reports_a_row_that_another_transaction_removed_first(
    db_session: Session,
) -> None:
    repository = DocumentRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))
    document = _document(db_session, workspace)
    kept = _document(db_session, workspace)
    db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document.id})

    assert repository.delete(document) is False

    assert repository.get(kept.id) is kept


def test_exists_asks_the_database_even_while_the_session_holds_the_document(
    db_session: Session,
) -> None:
    repository = DocumentRepository(db_session)
    document = _document(db_session, _workspace(db_session, _user(db_session)))
    assert repository.exists(document.id) is True

    db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document.id})

    # The session still holds the loaded copy; only a query sees that the row is gone.
    assert repository.exists(document.id) is False
    assert repository.exists(uuid.uuid4()) is False


def test_mark_for_retry_sends_a_retryable_document_back_to_uploaded(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))
    document = _document(
        db_session,
        workspace,
        "failed",
        error_message="The PDF could not be read.",
        attempts=2,
        updated_at=_NOW - timedelta(minutes=1),
    )

    assert repository.mark_for_retry(document.id, workspace.id, _NOW) is True

    loaded = (document.status, document.error_code, document.error_message, document.updated_at)
    db_session.expire_all()
    stored = (document.status, document.error_code, document.error_message, document.updated_at)
    assert loaded == stored == ("uploaded", None, None, _NOW)
    assert document.attempts == 2


def test_mark_for_retry_changes_nothing_when_the_document_may_not_be_retried(
    db_session: Session,
) -> None:
    repository = DocumentRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    other = _workspace(db_session, owner, "Other")
    moving = _document(db_session, workspace, "processing", updated_at=_NOW)
    failed = _document(db_session, workspace, "failed", updated_at=_NOW)

    assert repository.mark_for_retry(moving.id, workspace.id, _NOW) is False
    # The workspace is part of the condition: a document is retried only through its own.
    assert repository.mark_for_retry(failed.id, other.id, _NOW) is False
    assert repository.mark_for_retry(uuid.uuid4(), workspace.id, _NOW) is False

    db_session.expire_all()
    assert (moving.status, failed.status, failed.error_code) == (
        "processing",
        "failed",
        "pdf_unreadable",
    )


def test_mark_queue_unavailable_fails_the_document_at_the_given_time(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))
    document = _document(db_session, workspace, "uploaded", attempts=1, updated_at=_NOW)

    # The same time as before must still be written, not replaced by the database clock.
    assert repository.mark_queue_unavailable(document.id, 1, "Not queued.", _NOW) is True
    assert repository.mark_queue_unavailable(uuid.uuid4(), 1, "Not queued.", _NOW) is False

    loaded = (document.status, document.error_code, document.error_message, document.updated_at)
    db_session.expire_all()
    stored = (document.status, document.error_code, document.error_message, document.updated_at)
    assert loaded == stored == ("failed", "queue_unavailable", "Not queued.", _NOW)
    assert document.attempts == 1


@pytest.mark.parametrize(
    ("status", "attempts", "error_code"),
    [("processing", 2, None), ("uploaded", 2, "ai_unavailable")],
    ids=["claimed", "waiting-for-a-retry"],
)
def test_mark_queue_unavailable_leaves_a_document_a_worker_has_moved_on(
    db_session: Session, status: DocumentStatus, attempts: int, error_code: str | None
) -> None:
    workspace = _workspace(db_session, _user(db_session))
    # Queued with attempts at 1; a worker has claimed it since.
    document = _document(
        db_session,
        workspace,
        status,
        attempts=attempts,
        error_code=error_code,
        updated_at=_EARLIER,
    )

    assert (
        DocumentRepository(db_session).mark_queue_unavailable(document.id, 1, "Not queued.", _NOW)
        is False
    )

    db_session.expire_all()
    assert (document.status, document.attempts, document.error_code, document.updated_at) == (
        status,
        attempts,
        error_code,
        _EARLIER,
    )


def test_claim_for_processing_starts_a_run_and_returns_what_the_run_needs(
    db_session: Session,
) -> None:
    workspace = _workspace(db_session, _user(db_session))
    # Waiting for a retry, with the analysis an earlier attempt saved.
    document = _document(
        db_session,
        workspace,
        "uploaded",
        attempts=1,
        error_code="ai_unavailable",
        error_message="The AI provider is busy.",
        title="Sorting",
        summary="How lists are put in order.",
        topics=["Merge sort", "Quick sort"],
        difficulty="medium",
        analysis_model="gpt-5.4-mini",
        updated_at=_EARLIER,
    )

    claimed = DocumentRepository(db_session).claim_for_processing(document.id, _NOW)

    assert claimed == ClaimedDocument(
        id=document.id,
        token=2,
        workspace_id=workspace.id,
        storage_key=document.storage_key,
        content_type="text/markdown",
        original_filename="notes.md",
        title="Sorting",
        summary="How lists are put in order.",
        topics=["Merge sort", "Quick sort"],
        difficulty="medium",
        analysis_model="gpt-5.4-mini",
    )
    db_session.expire_all()
    assert (
        document.status,
        document.attempts,
        document.processing_started_at,
        document.updated_at,
        document.error_code,
        document.error_message,
    ) == ("processing", 2, _NOW, _NOW, None, None)


@pytest.mark.parametrize("status", ["processing", "indexing", "ready", "failed"])
def test_claim_for_processing_leaves_a_document_that_is_not_uploaded(
    db_session: Session, status: DocumentStatus
) -> None:
    workspace = _workspace(db_session, _user(db_session))
    document = _document(db_session, workspace, status, attempts=1, updated_at=_EARLIER)

    assert DocumentRepository(db_session).claim_for_processing(document.id, _NOW) is None

    db_session.expire_all()
    assert (document.status, document.attempts, document.updated_at) == (status, 1, _EARLIER)


def test_claim_for_processing_gives_a_document_to_one_run_only(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    document = _document(db_session, _workspace(db_session, _user(db_session)))

    first = repository.claim_for_processing(document.id, _NOW)
    second = repository.claim_for_processing(document.id, _NOW)

    assert first is not None
    assert first.token == 1
    assert second is None
    assert repository.claim_for_processing(uuid.uuid4(), _NOW) is None


@pytest.mark.parametrize("write", _RUN_WRITES.values(), ids=_RUN_WRITES.keys())
def test_a_run_whose_token_is_no_longer_current_writes_nothing(
    db_session: Session, write: Callable[[DocumentRepository, uuid.UUID, int], bool]
) -> None:
    repository = DocumentRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))
    # A later run has claimed the document since run 1 did.
    document = _document(db_session, workspace, "processing", attempts=2, updated_at=_EARLIER)

    assert write(repository, document.id, 1) is False
    assert write(repository, uuid.uuid4(), 2) is False

    db_session.expire_all()
    assert (
        document.status,
        document.updated_at,
        document.word_count,
        document.error_code,
        document.chunk_count,
    ) == ("processing", _EARLIER, None, None, None)


def test_update_if_current_writes_the_values_at_the_given_time(db_session: Session) -> None:
    workspace = _workspace(db_session, _user(db_session))
    document = _document(db_session, workspace, "processing", attempts=2, updated_at=_EARLIER)

    updated = DocumentRepository(db_session).update_if_current(
        document.id, 2, _NOW, status="indexing", word_count=42, topics=["Sorting"]
    )

    assert updated is True
    loaded = (document.status, document.word_count, document.topics, document.updated_at)
    db_session.expire_all()
    stored = (document.status, document.word_count, document.topics, document.updated_at)
    assert loaded == stored == ("indexing", 42, ["Sorting"], _NOW)
    assert document.attempts == 2


def test_mark_failed_records_the_error_and_cuts_a_long_message_to_its_column(
    db_session: Session,
) -> None:
    workspace = _workspace(db_session, _user(db_session))
    document = _document(db_session, workspace, "indexing", attempts=1, updated_at=_EARLIER)

    failed = DocumentRepository(db_session).mark_failed(
        document.id, 1, "internal_error", "word " * 1000, _NOW
    )

    assert failed is True
    db_session.expire_all()
    assert (document.status, document.error_code, document.updated_at) == (
        "failed",
        "internal_error",
        _NOW,
    )
    assert document.error_message is not None
    assert len(document.error_message) <= ERROR_MESSAGE_MAX_LENGTH
    assert document.error_message.startswith("word word")


def test_mark_retry_pending_sends_the_document_back_to_uploaded_with_its_error(
    db_session: Session,
) -> None:
    workspace = _workspace(db_session, _user(db_session))
    document = _document(db_session, workspace, "indexing", attempts=1, updated_at=_EARLIER)

    pending = DocumentRepository(db_session).mark_retry_pending(
        document.id, 1, "ai_unavailable", "The AI provider is busy.", _NOW
    )

    assert pending is True
    db_session.expire_all()
    assert (
        document.status,
        document.error_code,
        document.error_message,
        document.updated_at,
        document.attempts,
    ) == ("uploaded", "ai_unavailable", "The AI provider is busy.", _NOW, 1)


def test_complete_marks_the_document_ready_at_the_given_time(db_session: Session) -> None:
    workspace = _workspace(db_session, _user(db_session))
    document = _document(
        db_session,
        workspace,
        "indexing",
        attempts=1,
        error_code="queue_unavailable",
        error_message="Not queued.",
        updated_at=_EARLIER,
    )

    completed = DocumentRepository(db_session).complete(
        document.id, 1, _NOW, chunk_count=3, embedding_model="mock-hashing-v1", processing_ms=1500
    )

    assert completed is True
    db_session.expire_all()
    assert (
        document.status,
        document.chunk_count,
        document.embedding_model,
        document.processing_ms,
        document.processed_at,
        document.updated_at,
        document.error_code,
        document.error_message,
    ) == ("ready", 3, "mock-hashing-v1", 1500, _NOW, _NOW, None, None)


def test_owner_usage_counts_active_documents_and_every_stored_byte(db_session: Session) -> None:
    repository = DocumentRepository(db_session)
    owner = _user(db_session)
    stranger = _user(db_session, "stranger@example.com")
    first = _workspace(db_session, owner, "First")
    second = _workspace(db_session, owner, "Second")
    _document(db_session, first, "uploaded", size_bytes=100)
    _document(db_session, first, "processing", size_bytes=200)
    _document(db_session, second, "indexing", size_bytes=300)
    _document(db_session, second, "ready", size_bytes=400)
    _document(db_session, second, "failed", size_bytes=500)
    _document(db_session, _workspace(db_session, stranger), "uploaded", size_bytes=10_000)

    usage = repository.owner_usage(owner.id)

    assert usage == OwnerUsage(active_count=3, storage_bytes=1500)
    assert type(usage.storage_bytes) is int
    assert repository.owner_usage(_user(db_session, "new@example.com").id) == (0, 0)


def test_list_embedded_by_another_model_lists_every_owners_ready_documents_oldest_first(
    db_session: Session,
) -> None:
    workspace = _workspace(db_session, _user(db_session))
    strangers = _workspace(db_session, _user(db_session, "stranger@example.com"))
    newest = _document(
        db_session,
        workspace,
        "ready",
        embedding_model=_OLDER_EMBEDDING_MODEL,
        attempts=1,
        created_at=_NOW,
    )
    oldest = _document(
        db_session,
        strangers,
        "ready",
        embedding_model=_OLDER_EMBEDDING_MODEL,
        attempts=3,
        created_at=_NOW - timedelta(days=2),
    )
    tied = [
        _document(
            db_session, workspace, "ready", embedding_model="older-model-v0", created_at=_EARLIER
        )
        for _ in range(2)
    ]
    # Embedded by the current model already, or not ready: whatever model they name.
    _document(db_session, workspace, "ready", created_at=_EARLIER)
    statuses: tuple[DocumentStatus, ...] = ("uploaded", "processing", "indexing", "failed")
    for status in statuses:
        _document(
            db_session,
            workspace,
            status,
            embedding_model=_OLDER_EMBEDDING_MODEL,
            created_at=_EARLIER,
        )

    candidates = DocumentRepository(db_session).list_embedded_by_another_model(
        _CURRENT_EMBEDDING_MODEL, _CHAT_MODEL
    )

    tied_by_id = sorted(tied, key=lambda document: document.id)
    assert [(candidate.id, candidate.attempts) for candidate in candidates] == [
        (oldest.id, 3),
        (tied_by_id[0].id, 0),
        (tied_by_id[1].id, 0),
        (newest.id, 1),
    ]


def test_list_embedded_by_another_model_tells_whose_saved_analysis_the_next_run_reuses(
    db_session: Session,
) -> None:
    workspace = _workspace(db_session, _user(db_session))

    def stale(minutes_ago: int, **analysis: object) -> Document:
        return _document(
            db_session,
            workspace,
            "ready",
            embedding_model=_OLDER_EMBEDDING_MODEL,
            created_at=_NOW - timedelta(minutes=minutes_ago),
            **analysis,
        )

    same_model = stale(4, analysis_model=_CHAT_MODEL, difficulty="medium")
    other_model = stale(3, analysis_model="mock-heuristic-v1", difficulty="medium")
    incomplete = stale(2, analysis_model=_CHAT_MODEL, difficulty=None)
    unnamed_model = stale(1, analysis_model=None, difficulty="easy")

    candidates = DocumentRepository(db_session).list_embedded_by_another_model(
        _CURRENT_EMBEDDING_MODEL, _CHAT_MODEL
    )

    assert [(candidate.id, candidate.reuses_analysis) for candidate in candidates] == [
        (same_model.id, True),
        (other_model.id, False),
        (incomplete.id, False),
        (unnamed_model.id, False),
    ]


def test_mark_for_reindex_sends_a_ready_document_of_another_model_back_to_uploaded(
    db_session: Session,
) -> None:
    repository = DocumentRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))
    # A ready document should hold no error; one left on it is cleared all the same.
    document = _document(
        db_session,
        workspace,
        "ready",
        embedding_model=_OLDER_EMBEDDING_MODEL,
        attempts=2,
        error_code="queue_unavailable",
        error_message="Not queued.",
        updated_at=_EARLIER,
    )

    assert repository.mark_for_reindex(document.id, _CURRENT_EMBEDDING_MODEL, _NOW) is True
    assert repository.mark_for_reindex(uuid.uuid4(), _CURRENT_EMBEDDING_MODEL, _NOW) is False

    loaded = (document.status, document.error_code, document.error_message, document.updated_at)
    db_session.expire_all()
    stored = (document.status, document.error_code, document.error_message, document.updated_at)
    assert loaded == stored == ("uploaded", None, None, _NOW)
    # The next claim moves the run counter on; the new run replaces the rest.
    assert (document.attempts, document.embedding_model, document.chunk_count) == (
        2,
        _OLDER_EMBEDDING_MODEL,
        2,
    )


@pytest.mark.parametrize(
    ("status", "embedding_model"),
    [
        ("ready", _CURRENT_EMBEDDING_MODEL),
        ("uploaded", _OLDER_EMBEDDING_MODEL),
        ("processing", _OLDER_EMBEDDING_MODEL),
        ("indexing", _OLDER_EMBEDDING_MODEL),
        ("failed", _OLDER_EMBEDDING_MODEL),
    ],
    ids=["ready-with-the-current-model", "uploaded", "processing", "indexing", "failed"],
)
def test_mark_for_reindex_leaves_a_document_that_is_not_a_ready_one_of_another_model(
    db_session: Session, status: DocumentStatus, embedding_model: str
) -> None:
    workspace = _workspace(db_session, _user(db_session))
    document = _document(
        db_session, workspace, status, embedding_model=embedding_model, updated_at=_EARLIER
    )

    marked = DocumentRepository(db_session).mark_for_reindex(
        document.id, _CURRENT_EMBEDDING_MODEL, _NOW
    )

    assert marked is False
    db_session.expire_all()
    assert (document.status, document.embedding_model, document.updated_at) == (
        status,
        embedding_model,
        _EARLIER,
    )


def test_replace_for_document_stores_the_rows_in_chunk_order(db_session: Session) -> None:
    repository = DocumentChunkRepository(db_session)
    document = _document(db_session, _workspace(db_session, _user(db_session)))
    rows = [
        _row(1, heading="Merge sort", page_start=2, page_end=3),
        _row(0, heading="Sorting", page_start=1, page_end=2),
    ]

    repository.replace_for_document(document.id, document.workspace_id, rows)

    chunks, total = repository.list_for_document(document.id, offset=0, limit=10)
    assert [
        (chunk.chunk_index, chunk.content, chunk.heading, chunk.page_start, chunk.page_end)
        for chunk in chunks
    ] == [
        (0, "Chunk number 0", "Sorting", 1, 2),
        (1, "Chunk number 1", "Merge sort", 2, 3),
    ]
    assert all(chunk.workspace_id == document.workspace_id for chunk in chunks)
    assert total == 2
    stored = db_session.scalars(
        select(DocumentChunk.embedding)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    assert stored == [_embedding(0), _embedding(1)]


def test_replace_for_document_drops_the_previous_chunks(db_session: Session) -> None:
    repository = DocumentChunkRepository(db_session)
    document = _document(db_session, _workspace(db_session, _user(db_session)))
    repository.replace_for_document(document.id, document.workspace_id, [_row(i) for i in range(3)])

    repository.replace_for_document(
        document.id, document.workspace_id, [_row(0, content="Fresh text")]
    )

    chunks, total = repository.list_for_document(document.id, offset=0, limit=10)
    assert [(chunk.chunk_index, chunk.content) for chunk in chunks] == [(0, "Fresh text")]
    assert total == 1


def test_replace_for_document_inserts_the_rows_in_batches(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.repositories.document_chunks.CHUNK_INSERT_BATCH_SIZE", 2)
    repository = DocumentChunkRepository(db_session)
    document = _document(db_session, _workspace(db_session, _user(db_session)))
    batch_sizes: list[int] = []

    def record_chunk_insert(**event_args: Any) -> None:
        if event_args["statement"].startswith("INSERT INTO document_chunks"):
            # A batch of one row is a plain execute() with that row's parameters.
            rows = len(event_args["parameters"]) if event_args["executemany"] else 1
            batch_sizes.append(rows)

    event.listen(db_session.connection(), "before_cursor_execute", record_chunk_insert, named=True)

    repository.replace_for_document(document.id, document.workspace_id, [_row(i) for i in range(5)])

    assert batch_sizes == [2, 2, 1]
    chunks, total = repository.list_for_document(document.id, offset=0, limit=10)
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3, 4]
    assert total == 5


def test_list_for_document_pages_without_loading_embeddings(db_session: Session) -> None:
    repository = DocumentChunkRepository(db_session)
    workspace = _workspace(db_session, _user(db_session))
    document = _document(db_session, workspace)
    neighbour = _document(db_session, workspace)
    repository.replace_for_document(document.id, workspace.id, [_row(i) for i in range(5)])
    repository.replace_for_document(neighbour.id, workspace.id, [_row(0)])

    chunks, total = repository.list_for_document(document.id, offset=1, limit=2)

    assert [chunk.chunk_index for chunk in chunks] == [1, 2]
    assert total == 5
    for chunk in chunks:
        assert {"embedding", "search_vector"} <= inspect(chunk).unloaded
        with pytest.raises(InvalidRequestError):
            _ = chunk.embedding
