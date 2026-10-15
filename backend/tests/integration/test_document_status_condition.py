import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.status import STALE_DOCUMENT_SECONDS, is_retryable, retryable_condition
from app.models.document import DOCUMENT_STATUSES, Document, DocumentStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository

pytestmark = pytest.mark.integration

_NOW: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
_STALE_AGE: Final = timedelta(seconds=STALE_DOCUMENT_SECONDS)
_AGES: Final = (
    timedelta(0),
    _STALE_AGE,
    _STALE_AGE + timedelta(microseconds=1),
    timedelta(days=30),
)
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 2, "embedding_model": "mock-hashing-v1", "processed_at": _NOW},
    "failed": {"error_code": "pdf_unreadable"},
}


def _workspace(session: Session) -> Workspace:
    owner = UserRepository(session).add(
        User(email="owner@example.com", password_hash="hash", display_name="Owner")
    )
    return WorkspaceRepository(session).add(Workspace(owner_id=owner.id, name="Algorithms"))


def _document(
    session: Session, workspace: Workspace, status: DocumentStatus, updated_at: datetime
) -> Document:
    document_id = uuid.uuid4()
    return DocumentRepository(session).add(
        Document(
            id=document_id,
            workspace_id=workspace.id,
            original_filename="notes.md",
            content_type="text/markdown",
            size_bytes=1024,
            sha256=hashlib.sha256(document_id.bytes).hexdigest(),
            storage_key=f"{workspace.id}/{document_id}.md",
            status=status,
            updated_at=updated_at,
            **_STATUS_FIELDS.get(status, {}),
        )
    )


def test_the_sql_condition_selects_exactly_the_documents_is_retryable_accepts(
    db_session: Session,
) -> None:
    workspace = _workspace(db_session)
    documents = [
        _document(db_session, workspace, status, _NOW - age)
        for status in DOCUMENT_STATUSES
        for age in _AGES
    ]

    selected = set(
        db_session.scalars(
            select(Document.id).where(
                Document.workspace_id == workspace.id, retryable_condition(_NOW)
            )
        )
    )

    expected = {
        document.id
        for document in documents
        if is_retryable(document.status, document.updated_at, _NOW)
    }
    assert selected == expected
    # Every failed row, plus the two stale rows of each in-progress status.
    assert len(expected) == len(_AGES) + 3 * 2
