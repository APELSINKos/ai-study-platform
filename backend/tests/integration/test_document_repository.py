import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.document_chunks import ChunkRow, DocumentChunkRepository
from app.repositories.documents import DocumentRepository, OwnerUsage
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository

pytestmark = pytest.mark.integration

_NOW: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 2, "embedding_model": "mock-hashing-v1", "processed_at": _NOW},
    "failed": {"error_code": "pdf_unreadable"},
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

    repository.delete(document)

    assert repository.get(document_id) is None
    remaining = db_session.scalars(
        select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
    ).all()
    assert remaining == []


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
