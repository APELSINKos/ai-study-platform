import hashlib
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi import UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import configure_logging
from app.documents.queue import QueueUnavailableError
from app.documents.status import STALE_DOCUMENT_SECONDS
from app.documents.storage import FileStorage
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.services.documents import DocumentService

pytestmark = pytest.mark.integration

_START: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
_MARKDOWN: Final = b"# Sorting\n\nMerge sort splits the list in half.\n"
# How long a publish to a broker that is down keeps retrying before it gives up.
_PUBLISH_GIVE_UP: Final = timedelta(seconds=24)
_STALE_AGE: Final = timedelta(seconds=STALE_DOCUMENT_SECONDS)
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 3, "embedding_model": "mock-hashing-v1", "processed_at": _START},
    "failed": {"error_code": "no_text"},
}


class _FakeClock:
    """A callable clock whose time only moves when told to."""

    def __init__(self, start: datetime = _START) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class _Queue:
    """Records queued documents; with the broker down, a publish takes a while, then fails."""

    def __init__(self, clock: _FakeClock) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.unavailable = False
        self._clock = clock

    def enqueue(self, document_id: uuid.UUID) -> None:
        if self.unavailable:
            self._clock.advance(_PUBLISH_GIVE_UP)
            raise QueueUnavailableError("The broker is not reachable.")
        self.enqueued.append(document_id)


class _CommitFailedError(Exception):
    pass


class _ReadOnlyStorage(FileStorage):
    """Storage whose files cannot be removed, like a volume mounted read-only."""

    def delete(self, key: str) -> bool:
        raise PermissionError(f"Permission denied: {key}")


# Setup rows are committed: a request that fails rolls back only its own work.
def _user(session: Session) -> User:
    user = UserRepository(session).add(
        User(email="owner@example.com", password_hash="hash", display_name="Owner")
    )
    session.commit()
    return user


def _workspace(session: Session, owner: User) -> Workspace:
    workspace = WorkspaceRepository(session).add(
        Workspace(owner_id=owner.id, name="Algorithms", updated_at=_START - timedelta(days=1))
    )
    session.commit()
    return workspace


def _document(
    session: Session, workspace: Workspace, status: DocumentStatus, **values: object
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
    document = DocumentRepository(session).add(Document(**fields))
    session.commit()
    return document


def _upload_file(
    content: bytes = _MARKDOWN, filename: str = "notes.md", *, size_known: bool = True
) -> UploadFile:
    return UploadFile(
        io.BytesIO(content), filename=filename, size=len(content) if size_known else None
    )


def _document_count(session: Session, workspace_id: uuid.UUID) -> int:
    statement = (
        select(func.count()).select_from(Document).where(Document.workspace_id == workspace_id)
    )
    return session.execute(statement).scalar_one()


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _stored_file(storage: FileStorage, document: Document) -> Path:
    with storage.temp_file() as temp:
        temp.write_bytes(_MARKDOWN)
        storage.commit_temp(temp, document.storage_key)
    return storage.path_for(document.storage_key)


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock()


@pytest.fixture
def queue(clock: _FakeClock) -> _Queue:
    return _Queue(clock)


@pytest.fixture
def service(
    db_session: Session, integration_settings: Settings, queue: _Queue, clock: _FakeClock
) -> DocumentService:
    storage = FileStorage(integration_settings.storage_dir)
    return DocumentService(db_session, storage, queue, integration_settings, clock)


@pytest.fixture
def read_only_service(
    db_session: Session, integration_settings: Settings, queue: _Queue, clock: _FakeClock
) -> DocumentService:
    storage = _ReadOnlyStorage(integration_settings.storage_dir)
    return DocumentService(db_session, storage, queue, integration_settings, clock)


@pytest.fixture
def owner(db_session: Session) -> User:
    return _user(db_session)


def test_upload_takes_its_times_from_the_clock_and_touches_the_workspace(
    db_session: Session, service: DocumentService, owner: User, queue: _Queue
) -> None:
    workspace = _workspace(db_session, owner)

    view = service.upload(user=owner, workspace_id=workspace.id, upload=_upload_file())

    db_session.expire_all()
    document = view.document
    assert (document.status, document.created_at, document.updated_at) == (
        "uploaded",
        _START,
        _START,
    )
    assert workspace.updated_at == _START
    assert view.can_retry is False
    assert queue.enqueued == [document.id]


def test_a_publish_failure_marks_the_document_failed_when_the_publish_gave_up(
    db_session: Session,
    service: DocumentService,
    owner: User,
    queue: _Queue,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    queue.unavailable = True
    workspace = _workspace(db_session, owner)

    view = service.upload(user=owner, workspace_id=workspace.id, upload=_upload_file())

    db_session.expire_all()
    document = view.document
    assert (document.status, document.error_code) == ("failed", "queue_unavailable")
    assert document.created_at == _START
    assert document.updated_at == _START + _PUBLISH_GIVE_UP
    assert view.can_retry is True
    [warning] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "document_not_queued"
    ]
    assert warning["level"] == "warning"
    assert warning["document_id"] == str(document.id)


def test_an_upload_deleted_while_the_broker_was_down_is_not_found(
    db_session: Session,
    service: DocumentService,
    owner: User,
    queue: _Queue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(db_session, owner)

    def deleted_while_the_broker_is_down(document_id: uuid.UUID) -> None:
        # The owner deletes the new document while the publish is still being retried.
        db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
        raise QueueUnavailableError("The broker is not reachable.")

    monkeypatch.setattr(queue, "enqueue", deleted_while_the_broker_is_down)

    with pytest.raises(NotFoundError) as exc_info:
        service.upload(user=owner, workspace_id=workspace.id, upload=_upload_file())

    assert exc_info.value.code == "document_not_found"


def test_the_quota_is_checked_again_with_the_real_size_once_the_row_is_in(
    db_session: Session,
    service: DocumentService,
    owner: User,
    integration_settings: Settings,
) -> None:
    integration_settings.max_storage_bytes_per_user = 100
    workspace = _workspace(db_session, owner)
    _document(db_session, workspace, "ready", size_bytes=60)
    # With no size known in advance, only the check after the insert can catch it.
    upload = _upload_file(b"x" * 41, "notes.txt", size_known=False)

    with pytest.raises(ConflictError) as exc_info:
        service.upload(user=owner, workspace_id=workspace.id, upload=upload)

    assert exc_info.value.code == "storage_quota_exceeded"
    assert _document_count(db_session, workspace.id) == 1
    assert _files(integration_settings.storage_dir) == []


def test_a_workspace_deleted_during_the_upload_is_not_found_and_keeps_no_file(
    service: DocumentService,
    owner: User,
    integration_settings: Settings,
    queue: _Queue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # It passes the ownership check, then disappears before the document row goes in.
    vanished = Workspace(id=uuid.uuid4(), owner_id=owner.id, name="Deleted")
    monkeypatch.setattr(WorkspaceRepository, "get_for_owner", lambda *_: vanished)

    with pytest.raises(NotFoundError) as exc_info:
        service.upload(user=owner, workspace_id=vanished.id, upload=_upload_file())

    assert exc_info.value.code == "workspace_not_found"
    assert _files(integration_settings.storage_dir) == []
    assert queue.enqueued == []


def test_a_failed_commit_leaves_neither_the_row_nor_the_file(
    db_session: Session,
    service: DocumentService,
    owner: User,
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(db_session, owner)

    def fail_commit() -> None:
        raise _CommitFailedError

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(_CommitFailedError):
        service.upload(user=owner, workspace_id=workspace.id, upload=_upload_file())

    assert _document_count(db_session, workspace.id) == 0
    assert _files(integration_settings.storage_dir) == []


def test_whether_a_document_can_be_retried_follows_the_clock(
    db_session: Session, service: DocumentService, owner: User, clock: _FakeClock
) -> None:
    workspace = _workspace(db_session, owner)
    on_the_boundary = _document(db_session, workspace, "processing", updated_at=_START - _STALE_AGE)
    stalled = _document(
        db_session,
        workspace,
        "processing",
        updated_at=_START - _STALE_AGE - timedelta(microseconds=1),
    )
    failed = _document(db_session, workspace, "failed", updated_at=_START)

    def can_retry() -> dict[uuid.UUID, bool]:
        views, total = service.list_for_workspace(
            user=owner, workspace_id=workspace.id, status=None, offset=0, limit=10
        )
        assert total == 3
        return {view.document.id: view.can_retry for view in views}

    assert can_retry() == {on_the_boundary.id: False, stalled.id: True, failed.id: True}
    clock.advance(timedelta(microseconds=1))
    assert can_retry() == {on_the_boundary.id: True, stalled.id: True, failed.id: True}


def test_delete_touches_the_workspace_with_the_clock_time(
    db_session: Session, service: DocumentService, owner: User, clock: _FakeClock
) -> None:
    workspace = _workspace(db_session, owner)
    document = _document(db_session, workspace, "ready")
    clock.advance(timedelta(minutes=5))

    service.delete(user=owner, document_id=document.id)

    db_session.expire_all()
    assert DocumentRepository(db_session).get(document.id) is None
    assert workspace.updated_at == _START + timedelta(minutes=5)


def test_delete_keeps_the_file_when_the_commit_fails(
    db_session: Session,
    service: DocumentService,
    owner: User,
    integration_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(db_session, owner)
    document = _document(db_session, workspace, "ready")
    path = _stored_file(FileStorage(integration_settings.storage_dir), document)

    def fail_commit() -> None:
        raise _CommitFailedError

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(_CommitFailedError):
        service.delete(user=owner, document_id=document.id)

    assert path.exists()


def test_delete_still_succeeds_and_logs_a_warning_when_the_file_cannot_be_removed(
    db_session: Session,
    read_only_service: DocumentService,
    owner: User,
    integration_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    workspace = _workspace(db_session, owner)
    document = _document(db_session, workspace, "failed")
    path = _stored_file(FileStorage(integration_settings.storage_dir), document)

    read_only_service.delete(user=owner, document_id=document.id)

    assert DocumentRepository(db_session).get(document.id) is None
    assert path.exists()
    [warning] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "document_file_not_deleted"
    ]
    assert warning["level"] == "warning"
    assert warning["document_id"] == str(document.id)
    assert warning["exception"][0]["exc_type"] == "PermissionError"
