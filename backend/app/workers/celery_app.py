# Needed because Task[Any, Any] is not subscriptable at runtime on Celery.
from __future__ import annotations

import sys
from typing import Any, Final

import structlog
from celery import Celery, Task, signals

from app.core.config import MIB, get_settings
from app.core.logging import configure_logging
from app.core.request_context import request_id_ctx

if sys.platform != "win32":
    import resource

TASK_REQUEST_ID_KEY: Final = "request_id"
PROCESS_DOCUMENT_TASK_NAME: Final = "documents.process"
TASK_SOFT_TIME_LIMIT_SECONDS: Final = 5 * 60
TASK_TIME_LIMIT_SECONDS: Final = TASK_SOFT_TIME_LIMIT_SECONDS + 60
DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS: Final = 10 * 60
DOCUMENT_TASK_TIME_LIMIT_SECONDS: Final = DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS + 60
MAX_RETRY_COUNTDOWN_SECONDS: Final = 5 * 60
# Redis redelivers a message still unacknowledged after this long, so it must outlast the
# longest run plus the longest retry countdown, or a document is processed twice.
BROKER_VISIBILITY_TIMEOUT_SECONDS: Final = 30 * 60
# Uploads publish inside the request: a dead broker must fail it before the web proxy's
# 30 s timeout, so every connect, read and publish retry is bounded. One retry gives up
# within about 21 s, which leaves the rest of the upload time; a second would take 29 s.
BROKER_CONNECT_TIMEOUT_SECONDS: Final = 3
BROKER_SOCKET_TIMEOUT_SECONDS: Final = 5
PUBLISH_MAX_RETRIES: Final = 1
# The largest documents allowed peak below 650 MiB (measured); two capped children fit in 2 GiB.
WORKER_CHILD_MEMORY_LIMIT_BYTES: Final = 768 * MIB


def create_celery_app() -> Celery:
    app = Celery(
        "ai_study_platform",
        broker=get_settings().redis_url,
        # The worker imports these modules at startup; it discards a message for a task that
        # no imported module defines.
        include=["app.workers.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        # A task is acknowledged only after it finishes, so a crashed worker's task is redelivered.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_soft_time_limit=TASK_SOFT_TIME_LIMIT_SECONDS,
        task_time_limit=TASK_TIME_LIMIT_SECONDS,
        broker_connection_retry_on_startup=True,
        broker_transport_options={
            "visibility_timeout": BROKER_VISIBILITY_TIMEOUT_SECONDS,
            "socket_connect_timeout": BROKER_CONNECT_TIMEOUT_SECONDS,
            "socket_timeout": BROKER_SOCKET_TIMEOUT_SECONDS,
        },
        task_publish_retry_policy={
            "max_retries": PUBLISH_MAX_RETRIES,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 1,
        },
        # Fresh child processes give back the memory that parsing large PDFs leaves behind.
        worker_max_tasks_per_child=50,
        worker_max_memory_per_child=512_000,  # KiB
        worker_hijack_root_logger=False,
    )
    return app


celery_app = create_celery_app()


@signals.setup_logging.connect
def _configure_worker_logging(**_: Any) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)


@signals.worker_process_init.connect
def _limit_child_memory(**_: Any) -> None:
    # A file that makes pypdf balloon then fails as unreadable on a MemoryError, instead of
    # the kernel killing the child and leaving its document stuck in processing.
    if sys.platform != "win32":
        limit = WORKER_CHILD_MEMORY_LIMIT_BYTES
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


@signals.before_task_publish.connect
def _attach_request_id(headers: dict[str, Any] | None = None, **_: Any) -> None:
    request_id = request_id_ctx.get()
    if headers is not None and request_id is not None:
        headers.setdefault(TASK_REQUEST_ID_KEY, request_id)


@signals.task_prerun.connect
def _bind_request_id(task: Task[Any, Any] | None = None, **_: Any) -> None:
    structlog.contextvars.clear_contextvars()
    request_id = getattr(task.request, TASK_REQUEST_ID_KEY, None) if task is not None else None
    if isinstance(request_id, str):
        request_id_ctx.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)


@signals.task_postrun.connect
def _forget_request_id(**_: Any) -> None:
    request_id_ctx.set(None)
    structlog.contextvars.clear_contextvars()
