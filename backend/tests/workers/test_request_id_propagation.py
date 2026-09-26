from collections.abc import Iterator
from typing import Final

import pytest
from celery import Celery
from celery.contrib.testing.worker import start_worker

from app.core.request_context import request_id_ctx
from app.workers.celery_app import celery_app

RESULT_TIMEOUT_SECONDS: Final = 10


@pytest.fixture
def memory_app() -> Iterator[Celery]:
    app = Celery("request-id-tests", broker="memory://", backend="cache+memory://")
    app.conf.broker_connection_retry_on_startup = True

    @app.task(name="tests.current_request_id")
    def current_request_id() -> str | None:
        return request_id_ctx.get()

    with start_worker(app, perform_ping_check=False, pool="solo"):
        yield app


def test_the_request_id_of_the_api_call_reaches_the_task(memory_app: Celery) -> None:
    token = request_id_ctx.set("req-1234567890")
    try:
        result = memory_app.tasks["tests.current_request_id"].delay()
    finally:
        request_id_ctx.reset(token)

    assert result.get(timeout=RESULT_TIMEOUT_SECONDS) == "req-1234567890"


def test_tasks_published_outside_a_request_have_no_request_id(memory_app: Celery) -> None:
    result = memory_app.tasks["tests.current_request_id"].delay()

    assert result.get(timeout=RESULT_TIMEOUT_SECONDS) is None


def test_worker_is_configured_for_at_least_once_delivery() -> None:
    conf = celery_app.conf

    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_soft_time_limit < conf.task_time_limit
    assert conf.accept_content == ["json"]
