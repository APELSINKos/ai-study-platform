"""The Celery task that processes an uploaded document."""

# Needed because Task[Any, Any] is not subscriptable at runtime on Celery.
from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import structlog
from celery import Task
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.core.timing import to_ms
from app.db.session import get_session_factory
from app.documents.pipeline import run_pipeline
from app.documents.storage import FileStorage
from app.llm.base import EmbeddingProvider, LLMProvider
from app.llm.factory import build_embedding_provider, build_llm_provider
from app.workers.celery_app import (
    DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS,
    DOCUMENT_TASK_TIME_LIMIT_SECONDS,
    MAX_RETRY_COUNTDOWN_SECONDS,
    PROCESS_DOCUMENT_TASK_NAME,
    celery_app,
)

logger = structlog.get_logger(__name__)

# How many more times a document is tried after its provider was unavailable.
DOCUMENT_TASK_MAX_RETRIES: Final = 2
# The first retry waits this long, each later one twice as long as the one before.
RETRY_BASE_COUNTDOWN_SECONDS: Final = 30


@dataclass(frozen=True, slots=True)
class PipelineDependencies:
    """What the processing pipeline works with in the worker."""

    session_factory: sessionmaker[Session]
    storage: FileStorage
    llm: LLMProvider
    embedder: EmbeddingProvider
    settings: Settings
    clock: Callable[[], datetime]


def build_pipeline_dependencies(settings: Settings) -> PipelineDependencies:
    """The database, file storage, providers and clock that the settings select."""
    return PipelineDependencies(
        session_factory=get_session_factory(settings.database_url),
        storage=FileStorage(settings.storage_dir),
        llm=build_llm_provider(settings),
        embedder=build_embedding_provider(settings),
        settings=settings,
        clock=utcnow,
    )


@celery_app.task(
    name=PROCESS_DOCUMENT_TASK_NAME,
    bind=True,
    # Celery would otherwise add the task to every app the process finalises.
    shared=False,
    max_retries=DOCUMENT_TASK_MAX_RETRIES,
    soft_time_limit=DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=DOCUMENT_TASK_TIME_LIMIT_SECONDS,
)
def process_document(self: Task[Any, Any], document_id: str) -> None:
    """Run the processing pipeline on an uploaded document.

    The pipeline records how the run ended on the document itself; this task only schedules
    the next attempt when a provider was unavailable.
    """
    # Left bound when the task ends, so that Celery's own retry and failure lines name the
    # document too; the task_postrun handler clears it.
    structlog.contextvars.bind_contextvars(document_id=document_id)
    retries = self.request.retries
    logger.info("document_processing_started", attempt=retries + 1)
    dependencies = build_pipeline_dependencies(get_settings())
    started = time.perf_counter()
    outcome = run_pipeline(
        uuid.UUID(document_id),
        session_factory=dependencies.session_factory,
        storage=dependencies.storage,
        llm=dependencies.llm,
        embedder=dependencies.embedder,
        settings=dependencies.settings,
        clock=dependencies.clock,
        final_attempt=retries >= DOCUMENT_TASK_MAX_RETRIES,
    )
    logger.info(
        "document_processing_finished",
        outcome=outcome.kind,
        duration_ms=to_ms(time.perf_counter() - started),
        chunk_count=outcome.chunk_count,
    )
    if outcome.kind == "failed":
        logger.warning("document_processing_failed", code=outcome.code)
    if outcome.kind == "retry":
        raise self.retry(countdown=retry_countdown(retries, outcome.retry_after_seconds))


def retry_countdown(retries: int, retry_after_seconds: float | None) -> float:
    """Seconds to wait before the next attempt of a task already retried `retries` times.

    The wait doubles with each retry, is never shorter than the provider asked for, and
    never longer than MAX_RETRY_COUNTDOWN_SECONDS.
    """
    backoff: float = RETRY_BASE_COUNTDOWN_SECONDS * 2**retries
    return min(MAX_RETRY_COUNTDOWN_SECONDS, max(backoff, retry_after_seconds or 0))
