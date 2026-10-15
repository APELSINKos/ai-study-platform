import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.logging import configure_logging
from app.documents.storage import FileStorage
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository, WorkspaceStatsRow
from app.schemas.workspaces import WorkspaceCreateRequest, WorkspaceUpdateRequest
from app.services.workspaces import WorkspaceService

pytestmark = pytest.mark.integration

_START: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
_EXAM_DATE: Final = date(2027, 1, 20)
_EMPTY_STATS: Final = WorkspaceStatsRow(
    document_count=0,
    ready_count=0,
    processing_count=0,
    failed_count=0,
    estimated_study_minutes=0,
)
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 3, "embedding_model": "mock-hashing-v1", "processed_at": _START},
    "failed": {"error_code": "no_text"},
}


class _FakeClock:
    """A callable clock whose time only moves when the test tells it to."""

    def __init__(self, start: datetime = _START) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class _CommitFailedError(Exception):
    pass


class _ReadOnlyStorage(FileStorage):
    """Storage whose folders cannot be removed, like a volume mounted read-only."""

    def delete_workspace(self, workspace_id: uuid.UUID) -> bool:
        raise PermissionError(f"Permission denied: {workspace_id}")


def _user(session: Session, email: str = "owner@example.com") -> User:
    return UserRepository(session).add(
        User(email=email, password_hash="hash", display_name="Owner")
    )


def _workspace(
    session: Session, owner: User, name: str = "Algorithms", *, updated_at: datetime = _START
) -> Workspace:
    return WorkspaceRepository(session).add(
        Workspace(
            owner_id=owner.id,
            name=name,
            description="Graphs and trees",
            exam_date=_EXAM_DATE,
            updated_at=updated_at,
        )
    )


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
    return DocumentRepository(session).add(Document(**fields))


def _store_file(storage: FileStorage, workspace_id: uuid.UUID) -> str:
    key = storage.key_for(workspace_id, uuid.uuid4(), ".md")
    with storage.temp_file() as temp:
        temp.write_bytes(b"# Lecture notes\n")
        storage.commit_temp(temp, key)
    return key


def _document_count(session: Session, workspace_id: uuid.UUID) -> int:
    statement = (
        select(func.count()).select_from(Document).where(Document.workspace_id == workspace_id)
    )
    return session.execute(statement).scalar_one()


def _assert_not_found(call: Callable[[], object]) -> None:
    with pytest.raises(NotFoundError) as exc_info:
        call()
    assert exc_info.value.code == "workspace_not_found"


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock()


@pytest.fixture
def storage(tmp_path: Path) -> FileStorage:
    return FileStorage(tmp_path / "uploads")


@pytest.fixture
def service(db_session: Session, storage: FileStorage, clock: _FakeClock) -> WorkspaceService:
    return WorkspaceService(db_session, storage, clock)


@pytest.fixture
def owner(db_session: Session) -> User:
    return _user(db_session)


def test_create_stores_the_workspace_with_the_clock_time_and_no_documents(
    db_session: Session, service: WorkspaceService, owner: User
) -> None:
    request = WorkspaceCreateRequest(
        name="Algorithms", description="Graphs and trees", exam_date=_EXAM_DATE
    )

    created = service.create(user=owner, request=request)

    assert created.stats == _EMPTY_STATS
    workspace = created.workspace
    db_session.expire_all()
    assert workspace.owner_id == owner.id
    assert (workspace.name, workspace.description, workspace.exam_date) == (
        "Algorithms",
        "Graphs and trees",
        _EXAM_DATE,
    )
    assert workspace.created_at == _START
    assert workspace.updated_at == _START


def test_get_returns_the_workspace_with_the_stats_of_its_documents(
    db_session: Session, service: WorkspaceService, owner: User
) -> None:
    workspace = _workspace(db_session, owner)
    _document(db_session, workspace, "ready", estimated_study_minutes=40)
    _document(db_session, workspace, "processing")
    _document(db_session, workspace, "failed")

    found = service.get(user=owner, workspace_id=workspace.id)

    assert found.workspace is workspace
    assert found.stats == WorkspaceStatsRow(
        document_count=3,
        ready_count=1,
        processing_count=1,
        failed_count=1,
        estimated_study_minutes=40,
    )


def test_list_for_user_returns_one_page_of_the_users_workspaces(
    db_session: Session, service: WorkspaceService, owner: User
) -> None:
    for day in range(3):
        _workspace(db_session, owner, f"Day {day}", updated_at=_START - timedelta(days=day))
    _workspace(db_session, _user(db_session, "stranger@example.com"), "Not mine")

    items, total = service.list_for_user(user=owner, offset=1, limit=1)

    assert [item.workspace.name for item in items] == ["Day 1"]
    assert items[0].stats == _EMPTY_STATS
    assert total == 3


def test_update_changes_only_the_fields_sent_and_sets_updated_at_from_the_clock(
    db_session: Session, service: WorkspaceService, owner: User, clock: _FakeClock
) -> None:
    workspace = _workspace(db_session, owner, "Draft")
    _document(db_session, workspace, "uploaded")
    clock.advance(timedelta(minutes=5))

    updated = service.update(
        user=owner,
        workspace_id=workspace.id,
        changes=WorkspaceUpdateRequest.model_validate({"name": "Algorithms"}),
    )

    db_session.expire_all()
    assert (workspace.name, workspace.description, workspace.exam_date) == (
        "Algorithms",
        "Graphs and trees",
        _EXAM_DATE,
    )
    assert workspace.updated_at == _START + timedelta(minutes=5)
    assert updated.stats.processing_count == 1


def test_update_with_explicit_nulls_clears_the_description_and_the_exam_date(
    db_session: Session, service: WorkspaceService, owner: User
) -> None:
    workspace = _workspace(db_session, owner, "Algorithms")

    service.update(
        user=owner,
        workspace_id=workspace.id,
        changes=WorkspaceUpdateRequest.model_validate({"description": None, "exam_date": None}),
    )

    db_session.expire_all()
    assert (workspace.name, workspace.description, workspace.exam_date) == (
        "Algorithms",
        None,
        None,
    )


def test_an_unknown_workspace_is_not_found(service: WorkspaceService, owner: User) -> None:
    missing = uuid.uuid4()
    changes = WorkspaceUpdateRequest(name="Renamed")

    _assert_not_found(lambda: service.get(user=owner, workspace_id=missing))
    _assert_not_found(lambda: service.update(user=owner, workspace_id=missing, changes=changes))
    _assert_not_found(lambda: service.delete(user=owner, workspace_id=missing))


def test_another_users_workspace_is_not_found_and_stays_unchanged(
    db_session: Session, service: WorkspaceService, owner: User, storage: FileStorage
) -> None:
    workspace = _workspace(db_session, owner, "Mine")
    _document(db_session, workspace, "ready")
    key = _store_file(storage, workspace.id)
    stranger = _user(db_session, "stranger@example.com")
    changes = WorkspaceUpdateRequest.model_validate({"name": "Taken", "description": None})

    _assert_not_found(lambda: service.get(user=stranger, workspace_id=workspace.id))
    _assert_not_found(
        lambda: service.update(user=stranger, workspace_id=workspace.id, changes=changes)
    )
    _assert_not_found(lambda: service.delete(user=stranger, workspace_id=workspace.id))

    db_session.expire_all()
    assert (workspace.name, workspace.description, workspace.updated_at) == (
        "Mine",
        "Graphs and trees",
        _START,
    )
    assert _document_count(db_session, workspace.id) == 1
    assert storage.path_for(key).exists()


def test_delete_removes_the_workspace_its_documents_and_its_folder(
    db_session: Session, service: WorkspaceService, owner: User, storage: FileStorage
) -> None:
    workspace = _workspace(db_session, owner)
    workspace_id = workspace.id
    _document(db_session, workspace, "ready")
    _store_file(storage, workspace_id)
    neighbour = _workspace(db_session, owner, "Neighbour")
    neighbour_key = _store_file(storage, neighbour.id)

    service.delete(user=owner, workspace_id=workspace_id)

    assert WorkspaceRepository(db_session).get_for_owner(workspace_id, owner.id) is None
    assert _document_count(db_session, workspace_id) == 0
    assert not storage.path_for(str(workspace_id)).exists()
    assert storage.path_for(neighbour_key).exists()


def test_delete_keeps_the_folder_when_the_commit_fails(
    db_session: Session,
    service: WorkspaceService,
    owner: User,
    storage: FileStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(db_session, owner)
    key = _store_file(storage, workspace.id)

    def _fail_commit() -> None:
        raise _CommitFailedError

    monkeypatch.setattr(db_session, "commit", _fail_commit)

    with pytest.raises(_CommitFailedError):
        service.delete(user=owner, workspace_id=workspace.id)

    assert storage.path_for(key).exists()


def test_delete_still_succeeds_and_logs_a_warning_when_the_folder_cannot_be_removed(
    db_session: Session,
    owner: User,
    clock: _FakeClock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    service = WorkspaceService(db_session, _ReadOnlyStorage(tmp_path), clock)
    workspace = _workspace(db_session, owner)

    service.delete(user=owner, workspace_id=workspace.id)

    assert WorkspaceRepository(db_session).get_for_owner(workspace.id, owner.id) is None
    [warning] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "workspace_files_not_deleted"
    ]
    assert warning["level"] == "warning"
    assert warning["workspace_id"] == str(workspace.id)
    assert warning["exception"][0]["exc_type"] == "PermissionError"
