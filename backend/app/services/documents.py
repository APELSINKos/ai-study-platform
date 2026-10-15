import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import psycopg
import structlog
from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, RateLimitedError
from app.documents.queue import DocumentQueue, QueueUnavailableError
from app.documents.status import is_retryable
from app.documents.storage import FileStorage
from app.documents.validation import (
    InspectedUpload,
    UploadInspector,
    content_type_for,
    copy_upload,
    extension_for,
    sanitize_filename,
)
from app.models.document import (
    ACTIVE_DOCUMENT_STATUSES,
    Document,
    DocumentContentType,
    DocumentStatus,
)
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.document_chunks import DocumentChunkRepository
from app.repositories.documents import DocumentRepository, OwnerUsage
from app.repositories.workspaces import WorkspaceRepository
from app.services.workspaces import workspace_not_found

logger = structlog.get_logger(__name__)

# Documents in progress finish within minutes, so a client may try again soon.
ACTIVE_DOCUMENTS_RETRY_AFTER_SECONDS: Final = 60
DUPLICATE_DOCUMENT_CONSTRAINT: Final = "uq_documents_workspace_id_sha256"
WORKSPACE_FOREIGN_KEY: Final = "fk_documents_workspace_id_workspaces"

_DOCUMENT_NOT_FOUND_MESSAGE: Final = "The document was not found."
_DOCUMENT_FILE_MISSING_MESSAGE: Final = "The original file of the document is no longer stored."
_DOCUMENT_NOT_RETRYABLE_MESSAGE: Final = (
    "Only a failed document, or one whose processing has stalled, can be processed again."
)
_DUPLICATE_DOCUMENT_MESSAGE: Final = "This file has already been uploaded to the workspace."
_TOO_MANY_ACTIVE_DOCUMENTS_MESSAGE: Final = (
    "Too many of your documents are still being processed. Try again in a minute."
)
_STORAGE_QUOTA_EXCEEDED_MESSAGE: Final = "The file does not fit into your storage quota."
_QUEUE_UNAVAILABLE_MESSAGE: Final = "The document could not be queued for processing."


@dataclass(frozen=True, slots=True)
class DocumentView:
    """A document with whether its owner may start processing it again at this moment."""

    document: Document
    can_retry: bool


@dataclass(frozen=True, slots=True)
class StoredFile:
    """The original file of a document, as a download sends it."""

    path: Path
    stat: os.stat_result
    content_type: DocumentContentType
    filename: str


def document_not_found() -> NotFoundError:
    """The error for a document that does not exist or belongs to another user."""
    return NotFoundError(_DOCUMENT_NOT_FOUND_MESSAGE, code="document_not_found")


def _duplicate_document() -> ConflictError:
    return ConflictError(_DUPLICATE_DOCUMENT_MESSAGE, code="duplicate_document")


def _document_not_retryable() -> ConflictError:
    return ConflictError(_DOCUMENT_NOT_RETRYABLE_MESSAGE, code="document_not_retryable")


def _violated_constraint(error: IntegrityError) -> str | None:
    if isinstance(error.orig, psycopg.Error):
        return error.orig.diag.constraint_name
    return None


class DocumentService:
    """A user's documents: upload, listing, viewing, chunks, download, deletion and retry."""

    def __init__(
        self,
        session: Session,
        storage: FileStorage,
        queue: DocumentQueue,
        settings: Settings,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session = session
        self._storage = storage
        self._queue = queue
        self._settings = settings
        self._clock = clock
        self._documents = DocumentRepository(session)
        self._chunks = DocumentChunkRepository(session)
        self._workspaces = WorkspaceRepository(session)

    def upload(self, *, user: User, workspace_id: uuid.UUID, upload: UploadFile) -> DocumentView:
        """Store a file as a new document of the workspace and queue it for processing.

        Nothing is written before the workspace's owner and the user's caps are checked.
        The file is read once, while it is copied and checked, and a temporary copy never
        outlives the request. If the queue cannot take the document, it is kept as failed
        with queue_unavailable, so the upload still succeeds and can be retried.
        """
        self._get_owned_workspace(user, workspace_id)
        self._check_caps(
            self._documents.owner_usage(user.id), new_documents=1, new_bytes=upload.size or 0
        )
        self._storage.sweep_temp()
        filename = sanitize_filename(upload.filename or "")
        extension = extension_for(filename)
        with self._storage.temp_file() as temp_path:
            # The handle must be closed before the file can be moved on Windows.
            with temp_path.open("wb") as destination:
                inspected = copy_upload(
                    upload.file,
                    destination,
                    UploadInspector(extension),
                    max_bytes=self._settings.max_upload_bytes,
                )
            if self._documents.get_by_sha256(workspace_id, inspected.sha256) is not None:
                raise _duplicate_document()
            document = self._new_document(workspace_id, filename, extension, inspected)
            self._save(document, temp_path, user)
        self._enqueue(document)
        return self._view(document, self._clock())

    def list_for_workspace(
        self,
        *,
        user: User,
        workspace_id: uuid.UUID,
        status: DocumentStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[DocumentView], int]:
        self._get_owned_workspace(user, workspace_id)
        documents, total = self._documents.list_for_workspace(workspace_id, status, offset, limit)
        now = self._clock()
        return [self._view(document, now) for document in documents], total

    def get(self, *, user: User, document_id: uuid.UUID) -> DocumentView:
        return self._view(self._get_owned(user, document_id), self._clock())

    def list_chunks(
        self, *, user: User, document_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[DocumentChunk], int]:
        """One page of the document's chunks in reading order, without their embeddings."""
        document = self._get_owned(user, document_id)
        return self._chunks.list_for_document(document.id, offset, limit)

    def get_file(self, *, user: User, document_id: uuid.UUID) -> StoredFile:
        document = self._get_owned(user, document_id)
        path = self._storage.path_for(document.storage_key)
        try:
            stat = path.stat()
        except FileNotFoundError as exc:
            logger.warning("document_file_missing", document_id=str(document.id))
            raise NotFoundError(
                _DOCUMENT_FILE_MISSING_MESSAGE, code="document_file_missing"
            ) from exc
        return StoredFile(
            path=path,
            stat=stat,
            content_type=document.content_type,
            filename=document.original_filename,
        )

    def delete(self, *, user: User, document_id: uuid.UUID) -> None:
        """Delete the document with its chunks, then its file.

        The file goes only after the commit, so a failed delete never loses it. If removing
        it fails, the document stays deleted: nothing can reach the file any more, so the
        request succeeds and the leftover file is only logged.
        """
        document = self._get_owned(user, document_id)
        if not self._documents.delete(document):
            # Another request deleted it after it was loaded; that request owns the file.
            raise document_not_found()
        self._workspaces.touch(document.workspace_id, self._clock())
        self._session.commit()
        try:
            self._storage.delete(document.storage_key)
        except OSError:
            logger.warning("document_file_not_deleted", document_id=str(document.id), exc_info=True)

    def retry(self, *, user: User, document_id: uuid.UUID) -> DocumentView:
        """Queue a failed or stalled document for processing again.

        Whether it may be retried is decided by one compare-and-set UPDATE, so two retries
        at once queue it once. A failed document becomes active again and must fit under
        the cap of active documents. A queue that cannot take it is handled as on upload.
        """
        document = self._get_owned(user, document_id)
        now = self._clock()
        # Checked first so that waiting for the cap is never suggested for a document that
        # cannot be retried anyway; the UPDATE below has the final word.
        if not is_retryable(document.status, document.updated_at, now):
            raise _document_not_retryable()
        # A stalled document is still counted as active, so retrying it adds none.
        reactivated = 0 if document.status in ACTIVE_DOCUMENT_STATUSES else 1
        self._check_active_documents(self._documents.owner_usage(user.id), reactivated)
        if not self._documents.mark_for_retry(document.id, document.workspace_id, now):
            raise _document_not_retryable()
        self._session.commit()
        self._enqueue(document)
        return self._view(document, self._clock())

    def _get_owned(self, user: User, document_id: uuid.UUID) -> Document:
        # Another user's document is reported exactly like a missing one.
        document = self._documents.get_for_owner(document_id, user.id)
        if document is None:
            raise document_not_found()
        return document

    def _get_owned_workspace(self, user: User, workspace_id: uuid.UUID) -> Workspace:
        # Another user's workspace is reported exactly like a missing one.
        workspace = self._workspaces.get_for_owner(workspace_id, user.id)
        if workspace is None:
            raise workspace_not_found()
        return workspace

    def _check_caps(self, usage: OwnerUsage, *, new_documents: int = 0, new_bytes: int = 0) -> None:
        self._check_active_documents(usage, new_documents)
        if usage.storage_bytes + new_bytes > self._settings.max_storage_bytes_per_user:
            raise ConflictError(_STORAGE_QUOTA_EXCEEDED_MESSAGE, code="storage_quota_exceeded")

    def _check_active_documents(self, usage: OwnerUsage, new_documents: int) -> None:
        if usage.active_count + new_documents > self._settings.max_active_documents_per_user:
            raise RateLimitedError(
                _TOO_MANY_ACTIVE_DOCUMENTS_MESSAGE,
                code="too_many_active_documents",
                headers={"Retry-After": str(ACTIVE_DOCUMENTS_RETRY_AFTER_SECONDS)},
            )

    def _new_document(
        self, workspace_id: uuid.UUID, filename: str, extension: str, inspected: InspectedUpload
    ) -> Document:
        document_id = uuid.uuid4()
        now = self._clock()
        return Document(
            id=document_id,
            workspace_id=workspace_id,
            original_filename=filename,
            content_type=content_type_for(filename),
            size_bytes=inspected.size_bytes,
            sha256=inspected.sha256,
            storage_key=self._storage.key_for(workspace_id, document_id, extension),
            status="uploaded",
            created_at=now,
            updated_at=now,
        )

    def _save(self, document: Document, temp_path: Path, user: User) -> None:
        """Insert the row and move its file to its key: both happen, or neither does."""
        self._insert(document)
        file_moved = False
        try:
            # The new row counts now, as does any upload committed since the first check.
            self._check_caps(self._documents.owner_usage(user.id))
            self._storage.commit_temp(temp_path, document.storage_key)
            file_moved = True
            self._workspaces.touch(document.workspace_id, document.updated_at)
            self._session.commit()
        except BaseException:
            self._session.rollback()
            if file_moved:
                self._storage.delete(document.storage_key)
            raise

    def _insert(self, document: Document) -> None:
        try:
            self._documents.add(document)
        except IntegrityError as exc:
            self._session.rollback()
            # Only a lost race gets here: the same file uploaded twice at once, or the
            # workspace deleted after the ownership check.
            constraint = _violated_constraint(exc)
            if constraint == DUPLICATE_DOCUMENT_CONSTRAINT:
                raise _duplicate_document() from exc
            if constraint == WORKSPACE_FOREIGN_KEY:
                raise workspace_not_found() from exc
            raise

    def _enqueue(self, document: Document) -> None:
        try:
            self._queue.enqueue(document.id)
        except QueueUnavailableError:
            logger.warning("document_not_queued", document_id=str(document.id), exc_info=True)
            # Unlike the worker's writes, not checked against a run token: an upload or a
            # retry is no run.
            marked = self._documents.mark_queue_unavailable(
                document.id, _QUEUE_UNAVAILABLE_MESSAGE, self._clock()
            )
            if not marked:
                # The broker takes seconds to give up; the owner may delete it meanwhile.
                raise document_not_found() from None
            self._session.commit()

    @staticmethod
    def _view(document: Document, now: datetime) -> DocumentView:
        return DocumentView(
            document=document, can_retry=is_retryable(document.status, document.updated_at, now)
        )
