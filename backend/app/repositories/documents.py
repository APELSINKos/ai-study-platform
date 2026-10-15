import uuid
from typing import NamedTuple

from sqlalchemy import BigInteger, ColumnElement, cast, delete, func, select
from sqlalchemy.orm import Session

from app.models.document import ACTIVE_DOCUMENT_STATUSES, Document, DocumentStatus
from app.models.workspace import Workspace


class OwnerUsage(NamedTuple):
    # Documents still waiting for, or going through, processing.
    active_count: int
    # Sum of the sizes of every stored file, whatever its status.
    storage_bytes: int


class DocumentRepository:
    """Direct database access for documents. Holds no business rules and never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, document: Document) -> Document:
        self._session.add(document)
        self._session.flush()
        return document

    def get(self, document_id: uuid.UUID) -> Document | None:
        return self._session.get(Document, document_id)

    def get_for_owner(self, document_id: uuid.UUID, owner_id: uuid.UUID) -> Document | None:
        statement = (
            select(Document)
            .join(Workspace, Workspace.id == Document.workspace_id)
            .where(Document.id == document_id, Workspace.owner_id == owner_id)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_sha256(self, workspace_id: uuid.UUID, sha256: str) -> Document | None:
        statement = select(Document).where(
            Document.workspace_id == workspace_id, Document.sha256 == sha256
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        status: DocumentStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Document], int]:
        criteria: list[ColumnElement[bool]] = [Document.workspace_id == workspace_id]
        if status is not None:
            criteria.append(Document.status == status)
        statement = (
            select(Document)
            .where(*criteria)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .offset(offset)
            .limit(limit)
        )
        documents = list(self._session.execute(statement).scalars())
        total_statement = select(func.count()).select_from(Document).where(*criteria)
        return documents, self._session.execute(total_statement).scalar_one()

    def delete(self, document: Document) -> bool:
        """Delete the document, its chunks with it; False when its row was already gone.

        A statement rather than Session.delete(): the unit of work only warns when the row
        has disappeared, so a concurrent delete could not be told apart.
        """
        statement = delete(Document).where(Document.id == document.id).returning(Document.id)
        return self._session.execute(statement).first() is not None

    def owner_usage(self, owner_id: uuid.UUID) -> OwnerUsage:
        statement = (
            select(
                func.count().filter(Document.status.in_(ACTIVE_DOCUMENT_STATUSES)),
                # sum() over bigint is numeric in PostgreSQL; cast it back to an integer.
                cast(func.coalesce(func.sum(Document.size_bytes), 0), BigInteger),
            )
            .join(Workspace, Workspace.id == Document.workspace_id)
            .where(Workspace.owner_id == owner_id)
        )
        active_count, storage_bytes = self._session.execute(statement).one()
        return OwnerUsage(active_count=active_count, storage_bytes=storage_bytes)
