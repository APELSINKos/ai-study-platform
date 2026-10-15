from typing import Final

from app.workers.celery_app import (
    BROKER_CONNECT_TIMEOUT_SECONDS,
    BROKER_SOCKET_TIMEOUT_SECONDS,
    BROKER_VISIBILITY_TIMEOUT_SECONDS,
    DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS,
    DOCUMENT_TASK_TIME_LIMIT_SECONDS,
    MAX_RETRY_COUNTDOWN_SECONDS,
    PUBLISH_MAX_RETRIES,
    celery_app,
)

# The Next.js /api rewrite gives up on a proxied request after 30 seconds.
WEB_PROXY_TIMEOUT_SECONDS: Final = 30


def test_redis_does_not_redeliver_a_document_task_that_may_still_be_running() -> None:
    visibility_timeout = celery_app.conf.broker_transport_options["visibility_timeout"]

    assert visibility_timeout > DOCUMENT_TASK_TIME_LIMIT_SECONDS + MAX_RETRY_COUNTDOWN_SECONDS


def test_a_publish_to_an_unreachable_broker_fails_before_the_web_proxy_gives_up() -> None:
    options = celery_app.conf.broker_transport_options
    policy = celery_app.conf.task_publish_retry_policy
    connect_seconds = options["socket_connect_timeout"]
    read_seconds = options["socket_timeout"]
    pauses = sum(
        min(policy["interval_start"] + retry * policy["interval_step"], policy["interval_max"])
        for retry in range(policy["max_retries"])
    )

    # On a pooled connection the failed publish waits out one read first; kombu then
    # reconnects up to max_retries + 1 times, pausing between attempts.
    worst_case_seconds = (
        read_seconds + (policy["max_retries"] + 1) * (connect_seconds + read_seconds) + pauses
    )

    assert worst_case_seconds < WEB_PROXY_TIMEOUT_SECONDS


def test_the_soft_limit_of_a_document_task_comes_before_the_hard_one() -> None:
    assert DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS < DOCUMENT_TASK_TIME_LIMIT_SECONDS


def test_broker_and_worker_are_configured_for_long_document_runs() -> None:
    conf = celery_app.conf

    assert conf.broker_transport_options == {
        "visibility_timeout": BROKER_VISIBILITY_TIMEOUT_SECONDS,
        "socket_connect_timeout": BROKER_CONNECT_TIMEOUT_SECONDS,
        "socket_timeout": BROKER_SOCKET_TIMEOUT_SECONDS,
    }
    assert conf.task_publish_retry_policy == {
        "max_retries": PUBLISH_MAX_RETRIES,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 1,
    }
    assert conf.worker_max_tasks_per_child == 50
    assert conf.worker_max_memory_per_child == 512_000
