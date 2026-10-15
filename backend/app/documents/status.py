"""When a document may be sent for processing again.

A failed document always may. One still waiting for, or going through, processing may once
its status has not changed for STALE_DOCUMENT_SECONDS: the run that owned it is gone. Every
status change sets updated_at, so updated_at is the time of the last change.
"""

from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import ColumnElement, and_, or_

from app.models.document import ACTIVE_DOCUMENT_STATUSES, Document, DocumentStatus

# Longer than a document task may run, so no live run can still own a stale document.
STALE_DOCUMENT_SECONDS: Final = 15 * 60
_STALE_AGE: Final = timedelta(seconds=STALE_DOCUMENT_SECONDS)


def is_retryable(status: DocumentStatus, updated_at: datetime, now: datetime) -> bool:
    if status == "failed":
        return True
    return status in ACTIVE_DOCUMENT_STATUSES and updated_at < now - _STALE_AGE


def retryable_condition(now: datetime) -> ColumnElement[bool]:
    """is_retryable as a condition on the documents table, for a compare-and-set UPDATE."""
    return or_(
        Document.status == "failed",
        and_(
            Document.status.in_(ACTIVE_DOCUMENT_STATUSES),
            Document.updated_at < now - _STALE_AGE,
        ),
    )
