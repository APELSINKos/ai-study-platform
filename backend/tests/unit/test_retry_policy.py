import pytest

from app.documents.status import STALE_DOCUMENT_SECONDS
from app.workers.celery_app import MAX_RETRY_COUNTDOWN_SECONDS
from app.workers.tasks import DOCUMENT_TASK_MAX_RETRIES, retry_countdown


@pytest.mark.parametrize(("retries", "expected_seconds"), [(0, 30), (1, 60), (2, 120)])
def test_each_retry_waits_twice_as_long_as_the_one_before(
    retries: int, expected_seconds: int
) -> None:
    assert retry_countdown(retries, None) == expected_seconds


def test_a_longer_wait_that_the_provider_asks_for_is_kept() -> None:
    assert retry_countdown(0, 95.5) == 95.5


def test_a_shorter_wait_that_the_provider_asks_for_does_not_shorten_the_backoff() -> None:
    assert retry_countdown(2, 1.5) == 120


@pytest.mark.parametrize(
    ("retries", "retry_after_seconds"), [(4, None), (60, None), (0, 3600.0), (1, 300.5)]
)
def test_no_wait_is_longer_than_five_minutes(
    retries: int, retry_after_seconds: float | None
) -> None:
    assert retry_countdown(retries, retry_after_seconds) == MAX_RETRY_COUNTDOWN_SECONDS == 300


def test_a_document_waiting_for_a_retry_does_not_turn_stale_before_the_retry_is_due() -> None:
    # The waiting document stays uploaded, which its owner may retry by hand once it is stale.
    longest_wait = max(
        retry_countdown(retries, 1e9) for retries in range(DOCUMENT_TASK_MAX_RETRIES)
    )

    assert longest_wait < STALE_DOCUMENT_SECONDS
