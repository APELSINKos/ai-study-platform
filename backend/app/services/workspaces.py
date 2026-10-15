import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Final

import structlog
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.exceptions import NotFoundError
from app.documents.storage import FileStorage
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.workspaces import WorkspaceRepository, WorkspaceWithStats
from app.schemas.workspaces import WorkspaceCreateRequest, WorkspaceUpdateRequest

logger = structlog.get_logger(__name__)

_WORKSPACE_NOT_FOUND_MESSAGE: Final = "The workspace was not found."


class WorkspaceService:
    """A user's workspaces with the statistics of their documents."""

    def __init__(
        self, session: Session, storage: FileStorage, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._session = session
        self._storage = storage
        self._clock = clock
        self._workspaces = WorkspaceRepository(session)

    def list_for_user(
        self, *, user: User, offset: int, limit: int
    ) -> tuple[list[WorkspaceWithStats], int]:
        return self._workspaces.list_for_owner(user.id, offset, limit)

    def create(self, *, user: User, request: WorkspaceCreateRequest) -> WorkspaceWithStats:
        now = self._clock()
        workspace = self._workspaces.add(
            Workspace(
                owner_id=user.id,
                name=request.name,
                description=request.description,
                exam_date=request.exam_date,
                created_at=now,
                updated_at=now,
            )
        )
        self._session.commit()
        return self._with_stats(workspace)

    def get(self, *, user: User, workspace_id: uuid.UUID) -> WorkspaceWithStats:
        return self._with_stats(self._get_owned(user, workspace_id))

    def update(
        self, *, user: User, workspace_id: uuid.UUID, changes: WorkspaceUpdateRequest
    ) -> WorkspaceWithStats:
        workspace = self._get_owned(user, workspace_id)
        sent = changes.model_fields_set
        if changes.name is not None:
            workspace.name = changes.name
        if "description" in sent:
            workspace.description = changes.description
        if "exam_date" in sent:
            workspace.exam_date = changes.exam_date
        workspace.updated_at = self._clock()
        self._session.commit()
        return self._with_stats(workspace)

    def delete(self, *, user: User, workspace_id: uuid.UUID) -> None:
        """Delete the workspace with its documents, then its files.

        The files go only after the commit, so a failed delete never loses them. If
        removing them fails, the workspace stays deleted: nothing can reach the files any
        more, so the request succeeds and the leftover folder is only logged.
        """
        self._workspaces.delete(self._get_owned(user, workspace_id))
        self._session.commit()
        try:
            self._storage.delete_workspace(workspace_id)
        except OSError:
            logger.warning(
                "workspace_files_not_deleted", workspace_id=str(workspace_id), exc_info=True
            )

    def _get_owned(self, user: User, workspace_id: uuid.UUID) -> Workspace:
        # Another user's workspace is reported exactly like a missing one.
        workspace = self._workspaces.get_for_owner(workspace_id, user.id)
        if workspace is None:
            raise NotFoundError(_WORKSPACE_NOT_FOUND_MESSAGE, code="workspace_not_found")
        return workspace

    def _with_stats(self, workspace: Workspace) -> WorkspaceWithStats:
        return WorkspaceWithStats(
            workspace=workspace, stats=self._workspaces.get_stats(workspace.id)
        )
