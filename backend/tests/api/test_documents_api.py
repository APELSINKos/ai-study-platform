import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any, Final, NamedTuple

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import (
    DbSession,
    DocumentQueueDep,
    SettingsDep,
    StorageDep,
    get_document_service,
)
from app.core.config import Settings
from app.core.logging import configure_logging
from app.documents.chunking import HEADING_SEPARATOR
from app.documents.queue import QueueUnavailableError
from app.documents.status import STALE_DOCUMENT_SECONDS
from app.documents.storage import FileStorage
from app.models.document import Document, DocumentErrorCode, DocumentStatus
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.repositories.document_chunks import ChunkRow, DocumentChunkRepository
from app.repositories.documents import DocumentRepository
from app.services.documents import DocumentService
from tests.api.conftest import QueuedDocument, RecordingDocumentQueue, csrf_headers

pytestmark = pytest.mark.integration

_WORKSPACES_PATH: Final = "/api/v1/workspaces"
_DOCUMENTS_PATH: Final = "/api/v1/documents"
_REQUEST_ID: Final = "retry-request-0001"
_START: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
_STALE_AGE: Final = timedelta(seconds=STALE_DOCUMENT_SECONDS)
_JUST_STALE: Final = _STALE_AGE + timedelta(microseconds=1)
_MARKDOWN: Final = b"# Sorting\n\nMerge sort splits the list in half.\n"
_TEXT: Final = "Конспект лекции: интегралы и производные.\n".encode()
# The upload checks only the signature; reading the PDF is the worker's job.
_PDF: Final = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 4, "embedding_model": "mock-hashing-v1", "processed_at": _START},
    "failed": {"error_code": "pdf_unreadable"},
}


class _RetryCase(NamedTuple):
    status: DocumentStatus
    error_code: DocumentErrorCode | None
    # How long ago the status last changed, by the clock of the request.
    age: timedelta


class _FakeClock:
    """A callable clock whose time only moves when the test tells it to."""

    def __init__(self, start: datetime = _START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def storage(integration_settings: Settings) -> FileStorage:
    return FileStorage(integration_settings.storage_dir)


@pytest.fixture
def clock(auth_app: FastAPI) -> _FakeClock:
    """Makes the document routes read the time from a clock the test moves."""
    fake = _FakeClock()

    def service_on_the_fake_clock(
        db: DbSession, files: StorageDep, queue: DocumentQueueDep, settings: SettingsDep
    ) -> DocumentService:
        return DocumentService(db, files, queue, settings, fake)

    auth_app.dependency_overrides[get_document_service] = service_on_the_fake_clock
    return fake


def _workspace_path(workspace_id: str) -> str:
    return f"{_WORKSPACES_PATH}/{workspace_id}"


def _document_path(document_id: str | uuid.UUID, suffix: str = "") -> str:
    return f"{_DOCUMENTS_PATH}/{document_id}{suffix}"


def _create_workspace(client: TestClient, name: str = "Algorithms") -> str:
    response = client.post(_WORKSPACES_PATH, json={"name": name}, headers=csrf_headers(client))
    assert response.status_code == HTTPStatus.CREATED
    workspace_id: str = response.json()["id"]
    return workspace_id


def _upload(
    client: TestClient, workspace_id: str, filename: str = "notes.md", content: bytes = _MARKDOWN
) -> dict[str, Any]:
    response = client.post(
        f"{_workspace_path(workspace_id)}/documents",
        files={"file": (filename, content, "application/octet-stream")},
        headers=csrf_headers(client),
    )
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    body: dict[str, Any] = response.json()
    return body


def _add_document(
    session: Session,
    storage: FileStorage,
    workspace_id: str,
    status: DocumentStatus = "uploaded",
    **values: object,
) -> Document:
    """A row with its stored file, committed so that a request rolling back keeps it."""
    document_id = uuid.uuid4()
    workspace = uuid.UUID(workspace_id)
    fields: dict[str, object] = {
        "id": document_id,
        "workspace_id": workspace,
        "original_filename": "notes.md",
        "content_type": "text/markdown",
        "size_bytes": len(_MARKDOWN),
        "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
        "storage_key": storage.key_for(workspace, document_id, ".md"),
        "status": status,
        **_STATUS_FIELDS.get(status, {}),
    }
    fields.update(values)
    document = DocumentRepository(session).add(Document(**fields))
    session.commit()
    with storage.temp_file() as temp:
        temp.write_bytes(_MARKDOWN)
        storage.commit_temp(temp, document.storage_key)
    return document


def _embedding(hot: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[hot] = 1.0
    return vector


def _chunk_row(
    index: int,
    content: str | None = None,
    *,
    heading: str | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
) -> ChunkRow:
    chunk_text = f"Chunk number {index}" if content is None else content
    return ChunkRow(
        chunk_index=index,
        content=chunk_text,
        heading=heading,
        page_start=page_start,
        page_end=page_end,
        char_count=len(chunk_text),
        embedding=_embedding(index),
    )


def _add_chunks(session: Session, document: Document, rows: list[ChunkRow]) -> None:
    DocumentChunkRepository(session).replace_for_document(document.id, document.workspace_id, rows)
    session.commit()


def _reloaded(session: Session, document_id: str | uuid.UUID) -> Document:
    session.expire_all()
    document = session.get(Document, uuid.UUID(str(document_id)))
    assert document is not None
    return document


def _chunk_count(session: Session, document_id: uuid.UUID) -> int:
    statement = (
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
    )
    return session.execute(statement).scalar_one()


def _chunks(client: TestClient, document_id: str | uuid.UUID, **params: int) -> dict[str, Any]:
    response = client.get(_document_path(document_id, "/chunks"), params=params)
    assert response.status_code == HTTPStatus.OK
    body: dict[str, Any] = response.json()
    return body


def _retry(
    client: TestClient, document_id: str | uuid.UUID, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return client.post(
        _document_path(document_id, "/retry"), headers={**csrf_headers(client), **(headers or {})}
    )


def _assert_error(response: httpx2.Response, status: HTTPStatus, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


# --- view -----------------------------------------------------------------------


def test_get_returns_the_document_as_the_upload_did(user_client: TestClient) -> None:
    workspace_id = _create_workspace(user_client)
    uploaded = _upload(user_client, workspace_id)

    response = user_client.get(_document_path(uploaded["id"]))

    assert response.status_code == HTTPStatus.OK
    assert response.json() == uploaded


def test_get_returns_the_analysis_of_a_ready_document(
    user_client: TestClient, db_session: Session, storage: FileStorage
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(
        db_session,
        storage,
        workspace_id,
        "ready",
        attempts=1,
        title="Sorting algorithms",
        summary="Merge sort and quick sort compared.",
        topics=["merge sort", "quick sort"],
        difficulty="medium",
        estimated_study_minutes=12,
        word_count=1800,
        analysis_model="mock-heuristic-v1",
        processing_ms=950,
        processing_started_at=_START - timedelta(seconds=1),
    )

    body = user_client.get(_document_path(document.id)).json()

    assert body["id"] == str(document.id)
    assert body["workspace_id"] == workspace_id
    assert (body["status"], body["error_code"], body["attempts"], body["can_retry"]) == (
        "ready",
        None,
        1,
        False,
    )
    assert (body["title"], body["summary"], body["topics"], body["difficulty"]) == (
        "Sorting algorithms",
        "Merge sort and quick sort compared.",
        ["merge sort", "quick sort"],
        "medium",
    )
    assert (
        body["estimated_study_minutes"],
        body["page_count"],
        body["word_count"],
        body["chunk_count"],
        body["processing_ms"],
    ) == (12, None, 1800, 4, 950)
    assert (body["analysis_model"], body["embedding_model"]) == (
        "mock-heuristic-v1",
        "mock-hashing-v1",
    )
    assert datetime.fromisoformat(body["processed_at"]) == _START
    assert not {"sha256", "storage_key", "error_message"} & body.keys()


def test_an_unknown_document_is_not_found_on_every_route(
    user_client: TestClient, document_queue: RecordingDocumentQueue
) -> None:
    document_id = uuid.uuid4()
    path = _document_path(document_id)

    responses = [
        user_client.get(path),
        user_client.get(f"{path}/chunks"),
        user_client.get(f"{path}/file"),
        user_client.delete(path, headers=csrf_headers(user_client)),
        _retry(user_client, document_id),
    ]

    for response in responses:
        _assert_error(response, HTTPStatus.NOT_FOUND, "document_not_found")
    assert document_queue.enqueued == []


def test_a_malformed_document_id_is_a_validation_error(user_client: TestClient) -> None:
    response = user_client.get(_document_path("not-a-uuid"))

    _assert_error(response, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == "document_id"


def test_documents_need_a_signed_in_user(auth_client: TestClient) -> None:
    response = auth_client.get(_document_path(uuid.uuid4()))

    _assert_error(response, HTTPStatus.UNAUTHORIZED, "not_authenticated")
    assert response.headers["www-authenticate"] == "Bearer"


# --- delete ---------------------------------------------------------------------


def test_delete_removes_the_document_its_chunks_and_its_file(
    user_client: TestClient, db_session: Session, storage: FileStorage, clock: _FakeClock
) -> None:
    workspace_id = _create_workspace(user_client)
    deleted = _add_document(db_session, storage, workspace_id, "ready")
    kept = _add_document(db_session, storage, workspace_id, "ready")
    _add_chunks(db_session, deleted, [_chunk_row(index) for index in range(3)])
    _add_chunks(db_session, kept, [_chunk_row(index) for index in range(2)])
    deleted_id, deleted_key = deleted.id, deleted.storage_key
    clock.advance(timedelta(minutes=5))

    response = user_client.delete(_document_path(deleted_id), headers=csrf_headers(user_client))

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert response.content == b""
    _assert_error(
        user_client.get(_document_path(deleted_id)), HTTPStatus.NOT_FOUND, "document_not_found"
    )
    assert not storage.path_for(deleted_key).exists()
    assert storage.path_for(kept.storage_key).exists()
    assert _chunk_count(db_session, deleted_id) == 0
    assert _chunk_count(db_session, kept.id) == 2
    workspace = user_client.get(_workspace_path(workspace_id)).json()
    assert workspace["stats"]["document_count"] == 1
    assert datetime.fromisoformat(workspace["updated_at"]) == _START + timedelta(minutes=5)


def test_delete_succeeds_when_the_file_is_already_gone(
    user_client: TestClient, db_session: Session, storage: FileStorage
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "failed")
    storage.delete(document.storage_key)

    response = user_client.delete(_document_path(document.id), headers=csrf_headers(user_client))

    assert response.status_code == HTTPStatus.NO_CONTENT
    _assert_error(
        user_client.get(_document_path(document.id)), HTTPStatus.NOT_FOUND, "document_not_found"
    )


def test_a_document_deleted_by_another_request_in_the_meantime_is_not_found(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "ready")
    load = DocumentRepository.get_for_owner

    def load_then_lose_the_row(
        repository: DocumentRepository, document_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Document | None:
        loaded = load(repository, document_id, owner_id)
        # Another request deletes the document right after this one has loaded it.
        db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
        return loaded

    monkeypatch.setattr(DocumentRepository, "get_for_owner", load_then_lose_the_row)

    response = user_client.delete(_document_path(document.id), headers=csrf_headers(user_client))

    _assert_error(response, HTTPStatus.NOT_FOUND, "document_not_found")
    # The file belongs to the request that deleted the row.
    assert storage.path_for(document.storage_key).exists()


# --- chunks ---------------------------------------------------------------------


def test_chunks_come_in_reading_order_one_page_at_a_time(
    user_client: TestClient, db_session: Session, storage: FileStorage
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "ready")
    neighbour = _add_document(db_session, storage, workspace_id, "ready")
    _add_chunks(db_session, document, [_chunk_row(index) for index in reversed(range(5))])
    _add_chunks(db_session, neighbour, [_chunk_row(0)])

    first = _chunks(user_client, document.id, page=1, page_size=2)
    last = _chunks(user_client, document.id, page=3, page_size=2)
    everything = _chunks(user_client, document.id)

    assert [chunk["chunk_index"] for chunk in first["items"]] == [0, 1]
    assert (first["total"], first["page"], first["page_size"]) == (5, 1, 2)
    assert [chunk["chunk_index"] for chunk in last["items"]] == [4]
    assert [chunk["chunk_index"] for chunk in everything["items"]] == [0, 1, 2, 3, 4]
    assert (everything["total"], everything["page"], everything["page_size"]) == (5, 1, 20)


def test_a_chunk_carries_its_text_heading_and_pages_but_never_its_embedding(
    user_client: TestClient, db_session: Session, storage: FileStorage
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "ready")
    content = "Merge sort splits the list in half and merges the sorted halves."
    heading = f"Sorting{HEADING_SEPARATOR}Merge sort"
    _add_chunks(
        db_session,
        document,
        [_chunk_row(0, content, heading=heading, page_start=2, page_end=3)],
    )
    chunk_id = db_session.scalars(
        select(DocumentChunk.id).where(DocumentChunk.document_id == document.id)
    ).one()

    body = _chunks(user_client, document.id)

    assert body["items"] == [
        {
            "id": str(chunk_id),
            "chunk_index": 0,
            "content": content,
            "heading": heading,
            "page_start": 2,
            "page_end": 3,
            "char_count": len(content),
        }
    ]


def test_a_document_without_chunks_lists_none(
    user_client: TestClient, db_session: Session, storage: FileStorage
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "processing")

    body = _chunks(user_client, document.id)

    assert (body["items"], body["total"]) == ([], 0)


def test_chunk_pages_are_bounded(user_client: TestClient) -> None:
    response = user_client.get(_document_path(uuid.uuid4(), "/chunks"), params={"page_size": 101})

    _assert_error(response, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == "page_size"


# --- download -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "disposition"),
    [
        (
            "notes.md",
            _MARKDOWN,
            "text/markdown; charset=utf-8",
            'attachment; filename="notes.md"',
        ),
        (
            "Конспект.txt",
            _TEXT,
            "text/plain; charset=utf-8",
            "attachment; filename*=utf-8''%D0%9A%D0%BE%D0%BD%D1%81%D0%BF%D0%B5%D0%BA%D1%82.txt",
        ),
        ("lecture.pdf", _PDF, "application/pdf", 'attachment; filename="lecture.pdf"'),
    ],
    ids=["markdown", "cyrillic-name", "pdf"],
)
def test_the_original_file_downloads_as_an_attachment(
    user_client: TestClient, filename: str, content: bytes, content_type: str, disposition: str
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _upload(user_client, workspace_id, filename, content)

    response = user_client.get(_document_path(document["id"], "/file"))

    assert response.status_code == HTTPStatus.OK
    assert response.content == content
    assert response.headers["content-type"] == content_type
    assert response.headers["content-disposition"] == disposition
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"


def test_a_document_whose_file_is_gone_cannot_be_downloaded(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "ready")
    storage.delete(document.storage_key)

    response = user_client.get(_document_path(document.id, "/file"))

    _assert_error(response, HTTPStatus.NOT_FOUND, "document_file_missing")
    [warning] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "document_file_missing"
    ]
    assert warning["level"] == "warning"
    assert warning["document_id"] == str(document.id)


# --- retry ----------------------------------------------------------------------


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize(
    "case",
    [
        _RetryCase("failed", "pdf_unreadable", timedelta(minutes=1)),
        _RetryCase("failed", "queue_unavailable", timedelta(0)),
        _RetryCase("processing", None, _JUST_STALE),
        _RetryCase("indexing", None, timedelta(days=2)),
        _RetryCase("uploaded", None, _JUST_STALE),
        _RetryCase("uploaded", "ai_unavailable", _JUST_STALE),
    ],
    ids=[
        "failed",
        "failed-just-now",
        "stalled-processing",
        "stalled-indexing",
        "stalled-uploaded",
        "stalled-retry-pending",
    ],
)
def test_a_failed_or_stalled_document_goes_back_to_the_queue(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
    case: _RetryCase,
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(
        db_session,
        storage,
        workspace_id,
        case.status,
        error_code=case.error_code,
        error_message="The previous run stopped." if case.error_code else None,
        attempts=1,
        updated_at=_START - case.age,
    )
    before = user_client.get(_document_path(document.id)).json()

    response = _retry(user_client, document.id, {"X-Request-ID": _REQUEST_ID})

    assert before["can_retry"] is True
    assert response.status_code == HTTPStatus.ACCEPTED
    body = response.json()
    assert (body["status"], body["error_code"], body["attempts"], body["can_retry"]) == (
        "uploaded",
        None,
        1,
        False,
    )
    assert datetime.fromisoformat(body["updated_at"]) == _START
    row = _reloaded(db_session, document.id)
    # The run counter is the worker's run token: only claiming a run moves it.
    assert (row.status, row.error_code, row.error_message, row.attempts, row.updated_at) == (
        "uploaded",
        None,
        None,
        1,
        _START,
    )
    assert document_queue.enqueued == [QueuedDocument(document.id, _REQUEST_ID)]
    assert user_client.get(_document_path(document.id)).json() == body


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize(
    "case",
    [
        _RetryCase("processing", None, timedelta(0)),
        _RetryCase("indexing", None, timedelta(minutes=14)),
        _RetryCase("uploaded", None, timedelta(minutes=1)),
        _RetryCase("uploaded", "ai_unavailable", timedelta(minutes=5)),
        _RetryCase("ready", None, timedelta(days=30)),
    ],
    ids=["processing", "indexing", "uploaded", "retry-pending", "ready"],
)
def test_a_document_that_is_moving_or_ready_cannot_be_retried(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
    case: _RetryCase,
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(
        db_session,
        storage,
        workspace_id,
        case.status,
        error_code=case.error_code,
        attempts=1,
        updated_at=_START - case.age,
    )
    before = user_client.get(_document_path(document.id)).json()

    response = _retry(user_client, document.id)

    assert before["can_retry"] is False
    _assert_error(response, HTTPStatus.CONFLICT, "document_not_retryable")
    row = _reloaded(db_session, document.id)
    assert (row.status, row.error_code, row.attempts, row.updated_at) == (
        case.status,
        case.error_code,
        1,
        _START - case.age,
    )
    assert document_queue.enqueued == []


def test_a_stalled_document_can_be_retried_exactly_when_can_retry_says_so(
    user_client: TestClient, db_session: Session, storage: FileStorage, clock: _FakeClock
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(
        db_session, storage, workspace_id, "processing", updated_at=_START - _STALE_AGE
    )
    path = _document_path(document.id)

    on_the_boundary = user_client.get(path).json()["can_retry"]
    refused = _retry(user_client, document.id)
    clock.advance(timedelta(microseconds=1))
    just_after = user_client.get(path).json()["can_retry"]
    accepted = _retry(user_client, document.id)

    assert on_the_boundary is False
    _assert_error(refused, HTTPStatus.CONFLICT, "document_not_retryable")
    assert just_after is True
    assert accepted.status_code == HTTPStatus.ACCEPTED
    assert accepted.json()["status"] == "uploaded"


@pytest.mark.usefixtures("clock")
def test_of_two_retries_at_once_only_one_queues_the_document(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(
        db_session, storage, workspace_id, "failed", updated_at=_START - timedelta(minutes=1)
    )
    load = DocumentRepository.get_for_owner

    def load_then_lose_the_race(
        repository: DocumentRepository, document_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Document | None:
        loaded = load(repository, document_id, owner_id)
        # The other retry of the same document wins between this load and the update.
        db_session.execute(
            text(
                "UPDATE documents SET status = 'uploaded', error_code = NULL,"
                " error_message = NULL, updated_at = :now WHERE id = :id"
            ),
            {"id": document_id, "now": _START},
        )
        return loaded

    monkeypatch.setattr(DocumentRepository, "get_for_owner", load_then_lose_the_race)

    response = _retry(user_client, document.id)

    _assert_error(response, HTTPStatus.CONFLICT, "document_not_retryable")
    assert document_queue.enqueued == []


@pytest.mark.usefixtures("clock")
def test_a_document_deleted_while_its_retry_was_starting_is_not_found(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(
        db_session, storage, workspace_id, "failed", updated_at=_START - timedelta(minutes=1)
    )
    load = DocumentRepository.get_for_owner

    def load_then_lose_the_row(
        repository: DocumentRepository, document_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Document | None:
        loaded = load(repository, document_id, owner_id)
        # The owner deletes the document in another tab between this load and the update.
        db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
        return loaded

    monkeypatch.setattr(DocumentRepository, "get_for_owner", load_then_lose_the_row)

    response = _retry(user_client, document.id)

    _assert_error(response, HTTPStatus.NOT_FOUND, "document_not_found")
    assert document_queue.enqueued == []


@pytest.mark.usefixtures("clock")
def test_a_retry_the_broker_cannot_take_leaves_the_document_failed_for_another_try(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
) -> None:
    document_queue.unavailable = True
    workspace_id = _create_workspace(user_client)
    document = _add_document(
        db_session,
        storage,
        workspace_id,
        "failed",
        error_code="no_text",
        attempts=1,
        updated_at=_START - timedelta(hours=1),
    )

    response = _retry(user_client, document.id)

    assert response.status_code == HTTPStatus.ACCEPTED
    body = response.json()
    assert (body["status"], body["error_code"], body["can_retry"]) == (
        "failed",
        "queue_unavailable",
        True,
    )
    row = _reloaded(db_session, document.id)
    assert (row.status, row.error_code, row.attempts, row.updated_at) == (
        "failed",
        "queue_unavailable",
        1,
        _START,
    )
    assert row.error_message is not None
    assert user_client.get(_document_path(document.id)).json() == body


@pytest.mark.usefixtures("clock")
def test_a_document_deleted_while_its_retry_could_not_be_queued_is_not_found(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "failed")

    def deleted_while_the_broker_is_down(document_id: uuid.UUID) -> None:
        # The owner deletes the document while the publish is still being retried.
        db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
        raise QueueUnavailableError("The broker is not reachable.")

    monkeypatch.setattr(document_queue, "enqueue", deleted_while_the_broker_is_down)

    response = _retry(user_client, document.id)

    _assert_error(response, HTTPStatus.NOT_FOUND, "document_not_found")


@pytest.mark.usefixtures("clock")
def test_a_retry_that_would_pass_the_active_document_cap_waits(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
) -> None:
    workspace_id = _create_workspace(user_client)
    for _ in range(9):
        _add_document(db_session, storage, workspace_id, "processing", updated_at=_START)
    stalled = _add_document(
        db_session, storage, workspace_id, "processing", updated_at=_START - _JUST_STALE
    )
    failed = _add_document(db_session, storage, workspace_id, "failed", updated_at=_START)
    ready = _add_document(db_session, storage, workspace_id, "ready", updated_at=_START)

    refused = _retry(user_client, failed.id)
    # Never retryable, so waiting for the cap would not help: the answer is the conflict.
    not_retryable = _retry(user_client, ready.id)
    # A stalled document already counts as active, so retrying it adds none.
    accepted = _retry(user_client, stalled.id)

    _assert_error(refused, HTTPStatus.TOO_MANY_REQUESTS, "too_many_active_documents")
    assert refused.headers["retry-after"] == "60"
    assert _reloaded(db_session, failed.id).status == "failed"
    _assert_error(not_retryable, HTTPStatus.CONFLICT, "document_not_retryable")
    assert accepted.status_code == HTTPStatus.ACCEPTED
    assert [queued.document_id for queued in document_queue.enqueued] == [stalled.id]


@pytest.mark.usefixtures("clock")
def test_retries_past_the_hourly_limit_of_a_user_are_rate_limited(
    user_client: TestClient,
    other_user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    integration_settings: Settings,
) -> None:
    integration_settings.document_retries_per_hour = 2
    workspace_id = _create_workspace(user_client)
    documents = [_add_document(db_session, storage, workspace_id, "failed") for _ in range(3)]
    other_document = _add_document(
        db_session, storage, _create_workspace(other_user_client), "failed"
    )

    accepted = [_retry(user_client, document.id) for document in documents[:2]]
    limited = _retry(user_client, documents[2].id)
    other_user = _retry(other_user_client, other_document.id)

    assert [response.status_code for response in accepted] == [HTTPStatus.ACCEPTED] * 2
    _assert_error(limited, HTTPStatus.TOO_MANY_REQUESTS, "rate_limited")
    assert int(limited.headers["retry-after"]) > 0
    assert _reloaded(db_session, documents[2].id).status == "failed"
    assert other_user.status_code == HTTPStatus.ACCEPTED


# --- two users and CSRF ---------------------------------------------------------


def test_another_users_document_is_not_found_and_stays_unchanged(
    user_client: TestClient,
    other_user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "failed", attempts=2)
    _add_chunks(db_session, document, [_chunk_row(0), _chunk_row(1)])
    path = _document_path(document.id)
    workspace_before = user_client.get(_workspace_path(workspace_id)).json()

    responses = [
        other_user_client.get(path),
        other_user_client.get(f"{path}/chunks"),
        other_user_client.get(f"{path}/file"),
        other_user_client.delete(path, headers=csrf_headers(other_user_client)),
        _retry(other_user_client, document.id),
    ]

    for response in responses:
        _assert_error(response, HTTPStatus.NOT_FOUND, "document_not_found")
    row = _reloaded(db_session, document.id)
    assert (row.status, row.error_code, row.attempts) == ("failed", "pdf_unreadable", 2)
    assert storage.path_for(row.storage_key).read_bytes() == _MARKDOWN
    assert _chunk_count(db_session, document.id) == 2
    assert document_queue.enqueued == []
    assert user_client.get(_workspace_path(workspace_id)).json() == workspace_before


def test_cookie_requests_that_change_a_document_need_the_csrf_header(
    user_client: TestClient,
    db_session: Session,
    storage: FileStorage,
    document_queue: RecordingDocumentQueue,
) -> None:
    workspace_id = _create_workspace(user_client)
    document = _add_document(db_session, storage, workspace_id, "failed")
    path = _document_path(document.id)

    responses = [user_client.delete(path), user_client.post(f"{path}/retry")]

    for response in responses:
        _assert_error(response, HTTPStatus.FORBIDDEN, "csrf_failed")
    row = _reloaded(db_session, document.id)
    assert (row.status, row.error_code, row.attempts) == ("failed", "pdf_unreadable", 0)
    assert storage.path_for(row.storage_key).exists()
    assert document_queue.enqueued == []


# --- OpenAPI --------------------------------------------------------------------


def test_openapi_documents_the_document_routes_and_their_errors(
    auth_client: TestClient,
) -> None:
    schema = auth_client.get("/openapi.json").json()

    item = schema["paths"]["/api/v1/documents/{document_id}"]
    chunks = schema["paths"]["/api/v1/documents/{document_id}/chunks"]["get"]
    download = schema["paths"]["/api/v1/documents/{document_id}/file"]["get"]
    retry = schema["paths"]["/api/v1/documents/{document_id}/retry"]["post"]
    statuses = {
        "get": set(item["get"]["responses"]),
        "delete": set(item["delete"]["responses"]),
        "chunks": set(chunks["responses"]),
        "file": set(download["responses"]),
        "retry": set(retry["responses"]),
    }
    assert statuses == {
        "get": {"200", "401", "404", "422"},
        "delete": {"204", "401", "403", "404", "422"},
        "chunks": {"200", "401", "404", "422"},
        "file": {"200", "401", "404", "422"},
        "retry": {"202", "401", "403", "404", "409", "422", "429"},
    }
    for operation in (item["get"], item["delete"], chunks, download, retry):
        assert operation["tags"] == ["documents"]
    assert retry["responses"]["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DocumentOut"
    }
    assert set(download["responses"]["200"]["content"]) == {
        "application/pdf",
        "text/markdown",
        "text/plain",
    }
    schemas = schema["components"]["schemas"]
    assert schemas["ChunkPage"]["properties"]["items"]["items"] == {
        "$ref": "#/components/schemas/ChunkOut"
    }
    chunk = schemas["ChunkOut"]
    assert set(chunk["properties"]) == {
        "id",
        "chunk_index",
        "content",
        "heading",
        "page_start",
        "page_end",
        "char_count",
    }
    assert set(chunk["required"]) == set(chunk["properties"])
