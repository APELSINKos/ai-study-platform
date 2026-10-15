from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from app.documents.status import STALE_DOCUMENT_SECONDS, is_retryable
from app.models.document import DocumentStatus
from app.workers.celery_app import DOCUMENT_TASK_TIME_LIMIT_SECONDS

_NOW: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
_STALE_AGE: Final = timedelta(seconds=STALE_DOCUMENT_SECONDS)
_TICK: Final = timedelta(microseconds=1)


def test_a_failed_document_can_be_retried_at_once_and_later() -> None:
    assert is_retryable("failed", _NOW, _NOW) is True
    assert is_retryable("failed", _NOW - timedelta(days=30), _NOW) is True


def test_a_ready_document_is_never_retried() -> None:
    assert is_retryable("ready", _NOW, _NOW) is False
    assert is_retryable("ready", _NOW - timedelta(days=30), _NOW) is False


@pytest.mark.parametrize("status", ["uploaded", "processing", "indexing"])
def test_a_document_in_progress_is_retryable_only_once_it_stopped_moving(
    status: DocumentStatus,
) -> None:
    assert is_retryable(status, _NOW, _NOW) is False
    assert is_retryable(status, _NOW - _STALE_AGE, _NOW) is False
    assert is_retryable(status, _NOW - _STALE_AGE - _TICK, _NOW) is True
    assert is_retryable(status, _NOW - timedelta(days=30), _NOW) is True


def test_a_document_task_still_running_never_makes_its_document_stale() -> None:
    assert STALE_DOCUMENT_SECONDS > DOCUMENT_TASK_TIME_LIMIT_SECONDS
