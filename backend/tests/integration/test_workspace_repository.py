import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository, WorkspaceStats

pytestmark = pytest.mark.integration

_NOW: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
_EMPTY_STATS: Final = WorkspaceStats(
    document_count=0,
    ready_count=0,
    processing_count=0,
    failed_count=0,
    estimated_study_minutes=0,
)
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 2, "embedding_model": "mock-hashing-v1", "processed_at": _NOW},
    "failed": {"error_code": "no_text"},
}


def _user(session: Session, email: str = "owner@example.com") -> User:
    return UserRepository(session).add(
        User(email=email, password_hash="hash", display_name="Owner")
    )


def _workspace(
    repository: WorkspaceRepository,
    owner: User,
    name: str = "Algorithms",
    *,
    updated_at: datetime = _NOW,
) -> Workspace:
    return repository.add(Workspace(owner_id=owner.id, name=name, updated_at=updated_at))


def _document(
    session: Session,
    workspace: Workspace,
    status: DocumentStatus = "uploaded",
    **values: object,
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
    document = Document(**fields)
    session.add(document)
    session.flush()
    return document


def _names(workspaces: list[Workspace]) -> list[str]:
    return [workspace.name for workspace in workspaces]


def test_add_assigns_an_id_and_get_for_owner_finds_the_workspace(db_session: Session) -> None:
    repository = WorkspaceRepository(db_session)
    owner = _user(db_session)

    workspace = repository.add(
        Workspace(owner_id=owner.id, name="Algorithms", description="Exam prep")
    )

    assert isinstance(workspace.id, uuid.UUID)
    assert repository.get_for_owner(workspace.id, owner.id) is workspace


def test_get_for_owner_hides_another_users_workspace(db_session: Session) -> None:
    repository = WorkspaceRepository(db_session)
    owner = _user(db_session)
    stranger = _user(db_session, "stranger@example.com")
    workspace = _workspace(repository, owner)

    assert repository.get_for_owner(workspace.id, stranger.id) is None
    assert repository.get_for_owner(uuid.uuid4(), owner.id) is None


def test_list_for_owner_puts_the_latest_update_first_and_breaks_ties_by_id(
    db_session: Session,
) -> None:
    repository = WorkspaceRepository(db_session)
    owner = _user(db_session)
    oldest = _workspace(repository, owner, "Oldest", updated_at=_NOW - timedelta(days=2))
    tied = [_workspace(repository, owner, f"Tied {number}", updated_at=_NOW) for number in range(3)]

    items, total = repository.list_for_owner(owner.id, offset=0, limit=10)

    tied_newest_first = sorted(tied, key=lambda workspace: workspace.id, reverse=True)
    assert [item.workspace for item in items] == [*tied_newest_first, oldest]
    assert total == 4


def test_list_for_owner_pages_and_counts_only_the_owners_workspaces(db_session: Session) -> None:
    repository = WorkspaceRepository(db_session)
    owner = _user(db_session)
    stranger = _user(db_session, "stranger@example.com")
    for day in range(5):
        _workspace(repository, owner, f"Day {day}", updated_at=_NOW - timedelta(days=day))
    _workspace(repository, stranger, "Not mine")

    page, total = repository.list_for_owner(owner.id, offset=2, limit=2)
    beyond, beyond_total = repository.list_for_owner(owner.id, offset=10, limit=2)

    assert _names([item.workspace for item in page]) == ["Day 2", "Day 3"]
    assert total == 5
    assert beyond == []
    assert beyond_total == 5


def test_list_for_owner_reports_document_stats_per_workspace(db_session: Session) -> None:
    repository = WorkspaceRepository(db_session)
    owner = _user(db_session)
    busy = _workspace(repository, owner, "Busy", updated_at=_NOW)
    empty = _workspace(repository, owner, "Empty", updated_at=_NOW - timedelta(days=1))
    for status in ("uploaded", "processing", "failed"):
        _document(db_session, busy, status)
    # Minutes of a document that is not ready yet stay out of the estimate.
    _document(db_session, busy, "indexing", estimated_study_minutes=30)
    _document(db_session, busy, "ready", estimated_study_minutes=10)
    _document(db_session, busy, "ready", estimated_study_minutes=15)
    _document(db_session, busy, "ready")

    items, _ = repository.list_for_owner(owner.id, offset=0, limit=10)

    stats = {item.workspace.name: item.stats for item in items}
    assert stats == {
        "Busy": WorkspaceStats(
            document_count=7,
            ready_count=3,
            processing_count=3,
            failed_count=1,
            estimated_study_minutes=25,
        ),
        "Empty": _EMPTY_STATS,
    }
    assert items[1].workspace is empty


def test_get_stats_counts_the_documents_of_one_workspace(db_session: Session) -> None:
    repository = WorkspaceRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(repository, owner, "Mine")
    neighbour = _workspace(repository, owner, "Neighbour")
    _document(db_session, workspace, "ready", estimated_study_minutes=20)
    _document(db_session, workspace, "uploaded")
    _document(db_session, neighbour, "failed")

    assert repository.get_stats(workspace.id) == WorkspaceStats(
        document_count=2,
        ready_count=1,
        processing_count=1,
        failed_count=0,
        estimated_study_minutes=20,
    )
    assert repository.get_stats(uuid.uuid4()) == _EMPTY_STATS


def test_touch_sets_updated_at_and_moves_the_workspace_to_the_top(db_session: Session) -> None:
    repository = WorkspaceRepository(db_session)
    owner = _user(db_session)
    stale = _workspace(repository, owner, "Stale", updated_at=_NOW - timedelta(days=3))
    _workspace(repository, owner, "Fresh", updated_at=_NOW)
    later = _NOW + timedelta(hours=1)

    repository.touch(stale.id, later)
    db_session.expire_all()

    items, _ = repository.list_for_owner(owner.id, offset=0, limit=10)
    assert _names([item.workspace for item in items]) == ["Stale", "Fresh"]
    assert stale.updated_at == later


def test_delete_removes_the_workspace(db_session: Session) -> None:
    repository = WorkspaceRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(repository, owner)
    workspace_id = workspace.id

    repository.delete(workspace)

    assert repository.get_for_owner(workspace_id, owner.id) is None
    assert repository.list_for_owner(owner.id, offset=0, limit=10) == ([], 0)
