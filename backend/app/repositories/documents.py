import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import BigInteger, ColumnElement, Update, cast, delete, func, select, update
from sqlalchemy.orm import Session

from app.documents.status import retryable_condition
from app.documents.text import shorten
from app.models.document import (
    ACTIVE_DOCUMENT_STATUSES,
    ERROR_MESSAGE_MAX_LENGTH,
    Difficulty,
    Document,
    DocumentContentType,
    DocumentErrorCode,
    DocumentStatus,
)
from app.models.workspace import Workspace


class OwnerUsage(NamedTuple):
    # Documents still waiting for, or going through, processing.
    active_count: int
    # Sum of the sizes of every stored file, whatever its status.
    storage_bytes: int


@dataclass(frozen=True, slots=True)
class ClaimedDocument:
    """What a processing run needs of the document it claimed.

    token is the attempts value the claim set: the run's later writes go through only while
    it is unchanged. The analysis fields hold what an earlier attempt saved, if any.
    """

    id: uuid.UUID
    token: int
    workspace_id: uuid.UUID
    storage_key: str
    content_type: DocumentContentType
    original_filename: str
    title: str | None
    summary: str | None
    topics: list[str] | None
    difficulty: Difficulty | None
    analysis_model: str | None


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

    def exists(self, document_id: uuid.UUID) -> bool:
        """Whether the row is still in the database, even while the session holds a copy."""
        statement = select(Document.id).where(Document.id == document_id)
        return self._session.execute(statement).first() is not None

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

    def mark_for_retry(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID, now: datetime
    ) -> bool:
        """Send the document back to uploaded if it may be retried at `now`; False if not.

        A single compare-and-set UPDATE, so of two retries at once only one succeeds. The
        run counter is left alone: the next claim moves it.
        """
        statement = (
            update(Document)
            .where(
                Document.id == document_id,
                Document.workspace_id == workspace_id,
                retryable_condition(now),
            )
            .values(status="uploaded", error_code=None, error_message=None, updated_at=now)
        )
        return self._update_returning(statement) is not None

    def mark_queue_unavailable(
        self, document_id: uuid.UUID, attempts: int, message: str, now: datetime
    ) -> bool:
        """Fail a document that could not be queued; False when it has moved on or is gone.

        A publish can fail after the broker took the message, and a worker may have claimed
        the document since. Every claim moves attempts on, so only a document still at the
        attempts it was queued with is failed.
        """
        statement = (
            update(Document)
            .where(Document.id == document_id, Document.attempts == attempts)
            .values(
                status="failed",
                error_code="queue_unavailable",
                error_message=message,
                updated_at=now,
            )
        )
        return self._update_returning(statement) is not None

    def claim_for_processing(self, document_id: uuid.UUID, now: datetime) -> ClaimedDocument | None:
        """Start a processing run on an uploaded document; None when it is not uploaded.

        A single compare-and-set UPDATE, so of two runs at once only one gets the document,
        and a document already claimed, finished or deleted is left alone.
        """
        statement = (
            update(Document)
            .where(Document.id == document_id, Document.status == "uploaded")
            .values(
                status="processing",
                attempts=Document.attempts + 1,
                processing_started_at=now,
                updated_at=now,
                error_code=None,
                error_message=None,
            )
        )
        document = self._update_returning(statement)
        if document is None:
            return None
        return ClaimedDocument(
            id=document.id,
            token=document.attempts,
            workspace_id=document.workspace_id,
            storage_key=document.storage_key,
            content_type=document.content_type,
            original_filename=document.original_filename,
            title=document.title,
            summary=document.summary,
            topics=document.topics,
            difficulty=document.difficulty,
            analysis_model=document.analysis_model,
        )

    def update_if_current(
        self, document_id: uuid.UUID, token: int, now: datetime, **values: object
    ) -> bool:
        """Write values to the document while the run with this token still owns it.

        False when the document is gone or a later run has claimed it; that run owns it now.
        """
        statement = (
            update(Document)
            .where(Document.id == document_id, Document.attempts == token)
            .values(**values, updated_at=now)
        )
        return self._update_returning(statement) is not None

    def mark_failed(
        self,
        document_id: uuid.UUID,
        token: int,
        code: DocumentErrorCode,
        message: str,
        now: datetime,
    ) -> bool:
        """End the run's document as failed with this error; False when the run lost it."""
        return self.update_if_current(
            document_id,
            token,
            now,
            status="failed",
            error_code=code,
            error_message=shorten(message, ERROR_MESSAGE_MAX_LENGTH),
        )

    def mark_retry_pending(
        self,
        document_id: uuid.UUID,
        token: int,
        code: DocumentErrorCode,
        message: str,
        now: datetime,
    ) -> bool:
        """Send the run's document back to uploaded with the error a later run may get past.

        False when the run lost it.
        """
        return self.update_if_current(
            document_id,
            token,
            now,
            status="uploaded",
            error_code=code,
            error_message=shorten(message, ERROR_MESSAGE_MAX_LENGTH),
        )

    def complete(self, document_id: uuid.UUID, token: int, now: datetime, **values: object) -> bool:
        """Mark the run's document ready, processed now; False when the run lost it.

        values are the rest a ready document needs: chunk_count, embedding_model and
        processing_ms. The UPDATE locks the document row until the transaction ends, so the
        caller stores the chunks after it, in the same transaction.
        """
        return self.update_if_current(
            document_id, token, now, status="ready", processed_at=now, **values
        )

    def _update_returning(self, statement: Update) -> Document | None:
        """Run an UPDATE of at most one document; the updated document, None if no row matched.

        The updated row is read back into the copy of the document this session holds,
        every column of it: a column left at its default on insert was never loaded, and
        synchronising only the changed values would leave it reading as None.
        """
        returning = statement.returning(Document).execution_options(
            synchronize_session=False, populate_existing=True
        )
        return self._session.scalars(returning).first()

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
