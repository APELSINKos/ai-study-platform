import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Label, Row, func, select, true, update
from sqlalchemy.orm import Session

from app.models.document import ACTIVE_DOCUMENT_STATUSES, Document
from app.models.workspace import Workspace


@dataclass(frozen=True, slots=True)
class WorkspaceStatsRow:
    document_count: int
    ready_count: int
    # Documents still waiting for, or going through, processing.
    processing_count: int
    failed_count: int
    # Summed over ready documents only.
    estimated_study_minutes: int


@dataclass(frozen=True, slots=True)
class WorkspaceWithStats:
    workspace: Workspace
    stats: WorkspaceStatsRow


def _stats_columns() -> tuple[Label[Any], ...]:
    """The per-workspace aggregate, labelled with the WorkspaceStatsRow field names."""
    is_ready = Document.status == "ready"
    is_active = Document.status.in_(ACTIVE_DOCUMENT_STATUSES)
    ready_minutes = func.sum(Document.estimated_study_minutes).filter(is_ready)
    return (
        func.count().label("document_count"),
        func.count().filter(is_ready).label("ready_count"),
        func.count().filter(is_active).label("processing_count"),
        func.count().filter(Document.status == "failed").label("failed_count"),
        func.coalesce(ready_minutes, 0).label("estimated_study_minutes"),
    )


def _stats_from(row: Row[Any]) -> WorkspaceStatsRow:
    return WorkspaceStatsRow(
        document_count=row.document_count,
        ready_count=row.ready_count,
        processing_count=row.processing_count,
        failed_count=row.failed_count,
        estimated_study_minutes=row.estimated_study_minutes,
    )


class WorkspaceRepository:
    """Direct database access for workspaces. Holds no business rules and never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, workspace: Workspace) -> Workspace:
        self._session.add(workspace)
        self._session.flush()
        return workspace

    def get_for_owner(self, workspace_id: uuid.UUID, owner_id: uuid.UUID) -> Workspace | None:
        statement = select(Workspace).where(
            Workspace.id == workspace_id, Workspace.owner_id == owner_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_stats(self, workspace_id: uuid.UUID) -> WorkspaceStatsRow:
        statement = select(*_stats_columns()).where(Document.workspace_id == workspace_id)
        return _stats_from(self._session.execute(statement).one())

    def list_for_owner(
        self, owner_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[WorkspaceWithStats], int]:
        # LATERAL aggregates only the workspaces on the requested page.
        stats = (
            select(*_stats_columns())
            .where(Document.workspace_id == Workspace.id)
            .lateral("workspace_stats")
        )
        statement = (
            select(Workspace, *stats.c)
            .join(stats, true())
            .where(Workspace.owner_id == owner_id)
            .order_by(Workspace.updated_at.desc(), Workspace.id.desc())
            .offset(offset)
            .limit(limit)
        )
        items = [
            WorkspaceWithStats(workspace=row.Workspace, stats=_stats_from(row))
            for row in self._session.execute(statement)
        ]
        total_statement = (
            select(func.count()).select_from(Workspace).where(Workspace.owner_id == owner_id)
        )
        return items, self._session.execute(total_statement).scalar_one()

    def touch(self, workspace_id: uuid.UUID, now: datetime) -> None:
        self._session.execute(
            update(Workspace).where(Workspace.id == workspace_id).values(updated_at=now)
        )

    def delete(self, workspace: Workspace) -> None:
        self._session.delete(workspace)
        self._session.flush()
