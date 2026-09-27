# Needed because Task[Any, Any] is not subscriptable at runtime on Celery.
from __future__ import annotations

from typing import Any, Final

import structlog
from celery import Celery, Task, signals

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.request_context import request_id_ctx

TASK_REQUEST_ID_KEY: Final = "request_id"
TASK_SOFT_TIME_LIMIT_SECONDS: Final = 5 * 60
TASK_TIME_LIMIT_SECONDS: Final = TASK_SOFT_TIME_LIMIT_SECONDS + 60


def create_celery_app() -> Celery:
    app = Celery("ai_study_platform", broker=get_settings().redis_url)
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
        worker_hijack_root_logger=False,
    )
    return app


celery_app = create_celery_app()


@signals.setup_logging.connect
def _configure_worker_logging(**_: Any) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)


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
