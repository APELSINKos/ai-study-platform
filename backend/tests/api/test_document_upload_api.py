import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any, Final, NamedTuple

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.documents.storage import FileStorage
from app.models.document import ERROR_MESSAGE_MAX_LENGTH, Document, DocumentStatus
from app.repositories.documents import DocumentRepository
from tests.api.conftest import QueuedDocument, RecordingDocumentQueue, csrf_headers

pytestmark = pytest.mark.integration

_WORKSPACES_PATH: Final = "/api/v1/workspaces"
_REQUEST_ID: Final = "upload-request-0001"
_MARKDOWN: Final = b"# Sorting\n\nMerge sort splits the list in half.\n"
_TEXT: Final = "Конспект лекции: интегралы и производные.\n".encode()
# The upload checks only the signature; reading the PDF is the worker's job.
_PDF: Final = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
_START: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 4, "embedding_model": "mock-hashing-v1", "processed_at": _START},
    "failed": {"error_code": "pdf_unreadable"},
}


class _UploadCase(NamedTuple):
    filename: str
    content: bytes
    content_type: str
    extension: str


def _workspace_path(workspace_id: str) -> str:
    return f"{_WORKSPACES_PATH}/{workspace_id}"


def _documents_path(workspace_id: str) -> str:
    return f"{_workspace_path(workspace_id)}/documents"


def _create_workspace(client: TestClient, name: str = "Algorithms") -> str:
    response = client.post(_WORKSPACES_PATH, json={"name": name}, headers=csrf_headers(client))
    assert response.status_code == HTTPStatus.CREATED
    workspace_id: str = response.json()["id"]
    return workspace_id


def _upload(
    client: TestClient,
    workspace_id: str,
    filename: str = "notes.md",
    content: bytes = _MARKDOWN,
    *,
    headers: dict[str, str] | None = None,
) -> httpx2.Response:
    return client.post(
        _documents_path(workspace_id),
        files={"file": (filename, content, "application/octet-stream")},
        headers={**csrf_headers(client), **(headers or {})},
    )


def _upload_named(
    client: TestClient, workspace_id: str, filename: bytes, *, charset: str = "utf-8"
) -> httpx2.Response:
    """An upload whose file name is sent exactly as given, in a body of this charset."""
    boundary = "upload-test-boundary"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="' + filename + b'"\r\n',
            b"Content-Type: text/plain\r\n\r\n",
            b"Lecture notes\n",
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    content_type = f"multipart/form-data; boundary={boundary}; charset={charset}"
    return client.post(
        _documents_path(workspace_id),
        content=body,
        headers={**csrf_headers(client), "Content-Type": content_type},
    )


def _uploaded(
    client: TestClient, workspace_id: str, filename: str = "notes.md", content: bytes = _MARKDOWN
) -> dict[str, Any]:
    response = _upload(client, workspace_id, filename, content)
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    body: dict[str, Any] = response.json()
    return body


def _list(client: TestClient, workspace_id: str, **params: str | int) -> dict[str, Any]:
    response = client.get(_documents_path(workspace_id), params=params)
    assert response.status_code == HTTPStatus.OK
    body: dict[str, Any] = response.json()
    return body


def _assert_error(response: httpx2.Response, status: HTTPStatus, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def _add_document(
    session: Session, workspace_id: str, status: DocumentStatus = "uploaded", **values: object
) -> Document:
    """A row added directly, committed so that a request rolling back keeps it."""
    document_id = uuid.uuid4()
    fields: dict[str, object] = {
        "id": document_id,
        "workspace_id": uuid.UUID(workspace_id),
        "original_filename": "notes.md",
        "content_type": "text/markdown",
        "size_bytes": 2048,
        "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
        "storage_key": f"{workspace_id}/{document_id}.md",
        "status": status,
        **_STATUS_FIELDS.get(status, {}),
    }
    fields.update(values)
    document = DocumentRepository(session).add(Document(**fields))
    session.commit()
    return document


def _documents_in(session: Session, workspace_id: str) -> list[Document]:
    session.expire_all()
    statement = select(Document).where(Document.workspace_id == uuid.UUID(workspace_id))
    return list(session.scalars(statement))


def _stored_files(settings: Settings) -> list[Path]:
    """Every file under the storage root, unfinished uploads included."""
    root = settings.storage_dir
    return sorted(path.resolve() for path in root.rglob("*") if path.is_file())


# --- upload -------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        _UploadCase("lecture.pdf", _PDF, "application/pdf", ".pdf"),
        _UploadCase("notes.md", _MARKDOWN, "text/markdown", ".md"),
        _UploadCase("Конспект.TXT", _TEXT, "text/plain", ".txt"),
    ],
    ids=["pdf", "markdown", "text"],
)
def test_an_upload_is_stored_queued_once_and_returned_as_uploaded(
    user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
    case: _UploadCase,
) -> None:
    workspace_id = _create_workspace(user_client)

    response = _upload(
        user_client,
        workspace_id,
        case.filename,
        case.content,
        headers={"X-Request-ID": _REQUEST_ID},
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    body = response.json()
    document_id = uuid.UUID(body["id"])
    assert body["workspace_id"] == workspace_id
    assert (body["original_filename"], body["content_type"], body["size_bytes"]) == (
        case.filename,
        case.content_type,
        len(case.content),
    )
    assert (body["status"], body["error_code"], body["attempts"], body["can_retry"]) == (
        "uploaded",
        None,
        0,
        False,
    )
    assert body["created_at"] == body["updated_at"]
    assert body["title"] is None
    assert not {"sha256", "storage_key", "error_message"} & body.keys()
    [document] = _documents_in(db_session, workspace_id)
    assert document.id == document_id
    assert document.sha256 == hashlib.sha256(case.content).hexdigest()
    assert document.storage_key == f"{workspace_id}/{document_id}{case.extension}"
    stored = FileStorage(integration_settings.storage_dir).path_for(document.storage_key)
    assert stored.read_bytes() == case.content
    assert _stored_files(integration_settings) == [stored]
    assert document_queue.enqueued == [QueuedDocument(document_id, _REQUEST_ID)]


def test_an_upload_counts_in_the_workspace_and_moves_it_to_the_top(
    user_client: TestClient,
) -> None:
    workspace_id = _create_workspace(user_client, "First")
    _create_workspace(user_client, "Second")
    before = user_client.get(_workspace_path(workspace_id)).json()

    _uploaded(user_client, workspace_id)

    after = user_client.get(_workspace_path(workspace_id)).json()
    assert datetime.fromisoformat(after["updated_at"]) > datetime.fromisoformat(
        before["updated_at"]
    )
    assert (after["stats"]["document_count"], after["stats"]["processing_count"]) == (1, 1)
    workspaces = user_client.get(_WORKSPACES_PATH).json()["items"]
    assert [workspace["name"] for workspace in workspaces] == ["First", "Second"]


def test_a_file_over_the_upload_limit_is_refused_and_nothing_is_kept(
    user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The body limit leaves room for the multipart overhead, so the endpoint must catch it.
    monkeypatch.setattr(integration_settings, "max_upload_bytes", 1024)
    workspace_id = _create_workspace(user_client)

    too_large = _upload(user_client, workspace_id, "notes.txt", b"x" * 1025)
    at_the_limit = _upload(user_client, workspace_id, "notes.txt", b"y" * 1024)

    _assert_error(too_large, HTTPStatus.CONTENT_TOO_LARGE, "payload_too_large")
    assert at_the_limit.status_code == HTTPStatus.ACCEPTED
    [document] = _documents_in(db_session, workspace_id)
    assert document.size_bytes == 1024
    assert [queued.document_id for queued in document_queue.enqueued] == [document.id]
    assert _stored_files(integration_settings) == [
        FileStorage(integration_settings.storage_dir).path_for(document.storage_key)
    ]


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("slides.pptx", b"PK\x03\x04 slides"),
        ("README", b"# Notes\n"),
        ("scan.pdf", b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048),
    ],
    ids=["other-extension", "no-extension", "pdf-without-signature"],
)
def test_files_other_than_pdf_markdown_and_text_are_refused(
    user_client: TestClient,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
    filename: str,
    content: bytes,
) -> None:
    workspace_id = _create_workspace(user_client)

    response = _upload(user_client, workspace_id, filename, content)

    _assert_error(response, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_file_type")
    assert _list(user_client, workspace_id)["total"] == 0
    assert _stored_files(integration_settings) == []
    assert document_queue.enqueued == []


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("empty.md", b"", "empty_file"),
        ("empty.pdf", b"", "empty_file"),
        ("utf16.txt", "Notes".encode("utf-16"), "invalid_text_encoding"),
        ("nul.md", b"# Notes\x00\n", "invalid_text_encoding"),
        ("latin1.txt", "Café".encode("latin-1"), "invalid_text_encoding"),
    ],
    ids=["empty-markdown", "empty-pdf", "utf-16", "nul", "not-utf-8"],
)
def test_empty_files_and_text_not_in_utf8_are_refused(
    user_client: TestClient,
    integration_settings: Settings,
    filename: str,
    content: bytes,
    code: str,
) -> None:
    workspace_id = _create_workspace(user_client)

    response = _upload(user_client, workspace_id, filename, content)

    _assert_error(response, HTTPStatus.UNPROCESSABLE_CONTENT, code)
    assert _list(user_client, workspace_id)["total"] == 0
    assert _stored_files(integration_settings) == []


def test_a_request_without_a_file_is_a_validation_error(user_client: TestClient) -> None:
    workspace_id = _create_workspace(user_client)

    response = user_client.post(
        _documents_path(workspace_id), data={"name": "notes.md"}, headers=csrf_headers(user_client)
    )

    _assert_error(response, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert [detail["field"] for detail in response.json()["error"]["details"]] == ["file"]


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("../../outside.txt", "outside.txt"),
        ("..\\..\\windows\\notes.md", "notes.md"),
        ("notes\u202efdp.txt", "notesfdp.txt"),
    ],
    ids=["posix-traversal", "windows-traversal", "bidi-override"],
)
def test_a_file_name_is_cleaned_and_never_becomes_part_of_a_path(
    user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    raw: str,
    cleaned: str,
) -> None:
    workspace_id = _create_workspace(user_client)

    body = _uploaded(user_client, workspace_id, raw, b"Lecture notes\n")

    assert body["original_filename"] == cleaned
    [document] = _documents_in(db_session, workspace_id)
    extension = Path(cleaned).suffix
    assert document.storage_key == f"{workspace_id}/{document.id}{extension}"
    root = integration_settings.storage_dir.resolve()
    assert _stored_files(integration_settings) == [
        root / workspace_id / f"{document.id}{extension}"
    ]


def test_a_surrogate_smuggled_in_by_the_body_charset_is_dropped_from_the_name(
    user_client: TestClient, db_session: Session
) -> None:
    workspace_id = _create_workspace(user_client)

    # In UTF-7, "+2D0-" is a lone surrogate, which PostgreSQL cannot store.
    response = _upload_named(user_client, workspace_id, b"notes+2D0-.txt", charset="utf-7")

    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    assert response.json()["original_filename"] == "notes.txt"
    [document] = _documents_in(db_session, workspace_id)
    assert document.original_filename == "notes.txt"


def test_quotes_a_browser_escaped_in_the_name_are_restored_for_the_download(
    user_client: TestClient,
) -> None:
    workspace_id = _create_workspace(user_client)

    # Browsers send a double quote in a multipart file name as %22.
    response = _upload_named(user_client, workspace_id, b"Lecture %22Intro%22.md")

    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    document = response.json()
    assert document["original_filename"] == 'Lecture "Intro".md'
    download = user_client.get(f"/api/v1/documents/{document['id']}/file")
    assert download.headers["content-disposition"] == (
        "attachment; filename*=utf-8''Lecture%20%22Intro%22.md"
    )


# --- duplicates and per-user caps ---------------------------------------------


def test_the_same_file_twice_in_a_workspace_is_a_conflict_but_another_workspace_takes_it(
    user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
) -> None:
    workspace_id = _create_workspace(user_client)
    other_workspace_id = _create_workspace(user_client, "Other")
    first = _uploaded(user_client, workspace_id, "notes.md")

    again = _upload(user_client, workspace_id, "renamed.md")
    elsewhere = _upload(user_client, other_workspace_id, "notes.md")

    _assert_error(again, HTTPStatus.CONFLICT, "duplicate_document")
    assert elsewhere.status_code == HTTPStatus.ACCEPTED
    assert [document.id for document in _documents_in(db_session, workspace_id)] == [
        uuid.UUID(first["id"])
    ]
    assert [queued.document_id for queued in document_queue.enqueued] == [
        uuid.UUID(first["id"]),
        uuid.UUID(elsewhere.json()["id"]),
    ]
    assert len(_stored_files(integration_settings)) == 2


def test_a_duplicate_that_slips_past_the_first_check_is_still_a_conflict(
    user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _create_workspace(user_client)
    first = _uploaded(user_client, workspace_id)
    # As when the same file arrives twice at once: neither request sees the other's row.
    monkeypatch.setattr(DocumentRepository, "get_by_sha256", lambda *_: None)

    response = _upload(user_client, workspace_id, "again.md")

    _assert_error(response, HTTPStatus.CONFLICT, "duplicate_document")
    assert [document.id for document in _documents_in(db_session, workspace_id)] == [
        uuid.UUID(first["id"])
    ]
    assert len(_stored_files(integration_settings)) == 1


def test_the_eleventh_active_document_waits_until_one_finishes(
    user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
) -> None:
    workspace_id = _create_workspace(user_client)
    other_workspace_id = _create_workspace(user_client, "Other")
    in_progress = [
        _add_document(db_session, other_workspace_id, status)
        for status in ("uploaded", "processing", "indexing") * 3
    ]
    # Finished documents do not count.
    _add_document(db_session, workspace_id, "ready")
    _add_document(db_session, workspace_id, "failed")

    tenth = _upload(user_client, workspace_id, "tenth.md", b"# Tenth\n")
    eleventh = _upload(user_client, workspace_id, "eleventh.md", b"# Eleventh\n")

    assert tenth.status_code == HTTPStatus.ACCEPTED
    _assert_error(eleventh, HTTPStatus.TOO_MANY_REQUESTS, "too_many_active_documents")
    assert eleventh.headers["retry-after"] == "60"
    assert len(_stored_files(integration_settings)) == 1
    assert len(document_queue.enqueued) == 1

    finished = in_progress[0]
    finished.status = "failed"
    finished.error_code = "no_text"
    db_session.commit()

    assert _upload(user_client, workspace_id, "eleventh.md", b"# Eleventh\n").status_code == (
        HTTPStatus.ACCEPTED
    )


def test_an_upload_over_the_storage_quota_is_refused_and_leaves_no_file(
    user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration_settings, "max_storage_bytes_per_user", 100)
    workspace_id = _create_workspace(user_client)
    # Failed and ready documents keep their files, so they count as well.
    _add_document(db_session, workspace_id, "failed", size_bytes=60)

    over = _upload(user_client, workspace_id, "over.txt", b"o" * 41)
    exactly = _upload(user_client, workspace_id, "exactly.txt", b"e" * 40)

    _assert_error(over, HTTPStatus.CONFLICT, "storage_quota_exceeded")
    assert exactly.status_code == HTTPStatus.ACCEPTED
    assert [queued.document_id for queued in document_queue.enqueued] == [
        uuid.UUID(exactly.json()["id"])
    ]
    assert len(_stored_files(integration_settings)) == 1


# --- access, CSRF and rate limits ---------------------------------------------


def test_another_users_workspace_takes_no_upload_and_lists_nothing(
    user_client: TestClient,
    other_user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
) -> None:
    workspace_id = _create_workspace(user_client)
    _uploaded(user_client, workspace_id)
    workspace_before = user_client.get(_workspace_path(workspace_id)).json()
    files_before = _stored_files(integration_settings)

    responses = [
        _upload(other_user_client, workspace_id, "intruder.md", b"# Mine now\n"),
        other_user_client.get(_documents_path(workspace_id)),
        _upload(other_user_client, str(uuid.uuid4()), "notes.md", b"# Notes\n"),
        other_user_client.get(_documents_path(str(uuid.uuid4()))),
    ]

    for response in responses:
        _assert_error(response, HTTPStatus.NOT_FOUND, "workspace_not_found")
    assert len(_documents_in(db_session, workspace_id)) == 1
    assert user_client.get(_workspace_path(workspace_id)).json() == workspace_before
    assert _stored_files(integration_settings) == files_before
    assert len(document_queue.enqueued) == 1


def test_a_cookie_upload_without_the_csrf_header_is_refused(
    user_client: TestClient,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
) -> None:
    workspace_id = _create_workspace(user_client)

    response = user_client.post(
        _documents_path(workspace_id), files={"file": ("notes.md", _MARKDOWN, "text/markdown")}
    )

    _assert_error(response, HTTPStatus.FORBIDDEN, "csrf_failed")
    assert _list(user_client, workspace_id)["total"] == 0
    assert _stored_files(integration_settings) == []
    assert document_queue.enqueued == []


def test_uploads_past_the_hourly_limit_of_a_user_are_rate_limited(
    user_client: TestClient,
    other_user_client: TestClient,
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration_settings, "uploads_per_hour", 2)
    workspace_id = _create_workspace(user_client)
    other_workspace_id = _create_workspace(other_user_client)
    for number in range(2):
        _uploaded(user_client, workspace_id, f"notes-{number}.md", f"# Notes {number}\n".encode())

    limited = _upload(user_client, workspace_id, "notes-2.md", b"# Notes 2\n")
    other_user = _upload(other_user_client, other_workspace_id, "notes-2.md", b"# Notes 2\n")

    _assert_error(limited, HTTPStatus.TOO_MANY_REQUESTS, "rate_limited")
    assert int(limited.headers["retry-after"]) > 0
    assert _list(user_client, workspace_id)["total"] == 2
    assert other_user.status_code == HTTPStatus.ACCEPTED


def test_an_upload_to_another_users_workspace_still_counts_against_the_limit(
    user_client: TestClient,
    other_user_client: TestClient,
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration_settings, "uploads_per_hour", 1)
    workspace_id = _create_workspace(user_client)
    other_workspace_id = _create_workspace(other_user_client)

    # Its whole body was received before the workspace could be checked.
    not_found = _upload(user_client, other_workspace_id)
    limited = _upload(user_client, workspace_id)

    _assert_error(not_found, HTTPStatus.NOT_FOUND, "workspace_not_found")
    _assert_error(limited, HTTPStatus.TOO_MANY_REQUESTS, "rate_limited")
    assert _list(other_user_client, other_workspace_id)["total"] == 0


# --- broker failure -------------------------------------------------------------


def test_an_upload_the_broker_cannot_take_is_kept_as_failed_for_a_retry(
    user_client: TestClient,
    db_session: Session,
    integration_settings: Settings,
    document_queue: RecordingDocumentQueue,
) -> None:
    document_queue.unavailable = True
    workspace_id = _create_workspace(user_client)

    response = _upload(user_client, workspace_id)

    assert response.status_code == HTTPStatus.ACCEPTED
    body = response.json()
    assert (body["status"], body["error_code"], body["can_retry"]) == (
        "failed",
        "queue_unavailable",
        True,
    )
    [document] = _documents_in(db_session, workspace_id)
    assert (document.status, document.error_code) == ("failed", "queue_unavailable")
    assert document.error_message is not None
    assert 0 < len(document.error_message) <= ERROR_MESSAGE_MAX_LENGTH
    # The file stays, so a retry has something to process.
    stored = FileStorage(integration_settings.storage_dir).path_for(document.storage_key)
    assert stored.read_bytes() == _MARKDOWN
    assert _list(user_client, workspace_id)["items"] == [body]


# --- list ---------------------------------------------------------------------


def test_the_list_returns_documents_as_the_upload_did(user_client: TestClient) -> None:
    workspace_id = _create_workspace(user_client)
    uploaded = _uploaded(user_client, workspace_id)

    listed = _list(user_client, workspace_id)

    assert listed == {"items": [uploaded], "total": 1, "page": 1, "page_size": 20}


def test_the_list_puts_the_newest_document_first_and_is_paginated(
    user_client: TestClient, db_session: Session
) -> None:
    workspace_id = _create_workspace(user_client)
    other_workspace_id = _create_workspace(user_client, "Other")
    _add_document(db_session, other_workspace_id)
    oldest_first = [
        _add_document(db_session, workspace_id, created_at=_START + timedelta(minutes=minute))
        for minute in range(5)
    ]
    newest_first = [str(document.id) for document in reversed(oldest_first)]

    first_page = _list(user_client, workspace_id, page=1, page_size=2)
    last_page = _list(user_client, workspace_id, page=3, page_size=2)
    beyond = _list(user_client, workspace_id, page=4, page_size=2)

    assert [item["id"] for item in first_page["items"]] == newest_first[:2]
    assert (first_page["total"], first_page["page"], first_page["page_size"]) == (5, 1, 2)
    assert [item["id"] for item in last_page["items"]] == newest_first[4:]
    assert (beyond["items"], beyond["total"]) == ([], 5)


def test_the_list_can_show_only_documents_in_one_status(
    user_client: TestClient, db_session: Session
) -> None:
    workspace_id = _create_workspace(user_client)
    failed = [
        _add_document(
            db_session, workspace_id, "failed", created_at=_START + timedelta(minutes=minute)
        )
        for minute in range(2)
    ]
    _add_document(db_session, workspace_id, "ready")
    _add_document(db_session, workspace_id, "processing")

    listed = _list(user_client, workspace_id, status="failed")
    invalid = user_client.get(_documents_path(workspace_id), params={"status": "deleted"})

    assert [item["id"] for item in listed["items"]] == [str(failed[1].id), str(failed[0].id)]
    assert listed["total"] == 2
    _assert_error(invalid, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert [detail["field"] for detail in invalid.json()["error"]["details"]] == ["status"]


def test_listed_documents_say_whether_processing_can_be_started_again(
    user_client: TestClient, db_session: Session
) -> None:
    workspace_id = _create_workspace(user_client)
    now = datetime.now(UTC)
    rows = {
        "failed": _add_document(db_session, workspace_id, "failed", updated_at=now),
        "ready": _add_document(
            db_session, workspace_id, "ready", updated_at=now - timedelta(days=1)
        ),
        "moving": _add_document(db_session, workspace_id, "processing", updated_at=now),
        "stalled": _add_document(
            db_session, workspace_id, "processing", updated_at=now - timedelta(hours=1)
        ),
    }

    can_retry = {
        item["id"]: item["can_retry"] for item in _list(user_client, workspace_id)["items"]
    }

    assert {name: can_retry[str(row.id)] for name, row in rows.items()} == {
        "failed": True,
        "ready": False,
        "moving": False,
        "stalled": True,
    }


# --- OpenAPI ------------------------------------------------------------------


def test_openapi_documents_the_document_routes_their_errors_and_types(
    auth_client: TestClient,
) -> None:
    schema = auth_client.get("/openapi.json").json()

    collection = schema["paths"]["/api/v1/workspaces/{workspace_id}/documents"]
    assert set(collection["post"]["responses"]) == {
        "202",
        "401",
        "403",
        "404",
        "409",
        "413",
        "415",
        "422",
        "429",
    }
    assert set(collection["get"]["responses"]) == {"200", "401", "404", "422"}
    assert collection["post"]["tags"] == collection["get"]["tags"] == ["documents"]
    assert "multipart/form-data" in collection["post"]["requestBody"]["content"]
    [status_filter] = [
        parameter for parameter in collection["get"]["parameters"] if parameter["name"] == "status"
    ]
    assert {"$ref": "#/components/schemas/DocumentStatus"} in status_filter["schema"]["anyOf"]
    schemas = schema["components"]["schemas"]
    document = schemas["DocumentOut"]
    assert not {"sha256", "storage_key", "error_message"} & document["properties"].keys()
    assert set(document["required"]) == set(document["properties"])
    assert document["properties"]["status"] == {"$ref": "#/components/schemas/DocumentStatus"}
    assert {"$ref": "#/components/schemas/DocumentErrorCode"} in document["properties"][
        "error_code"
    ]["anyOf"]
    assert schemas["DocumentPage"]["properties"]["items"]["items"] == {
        "$ref": "#/components/schemas/DocumentOut"
    }
