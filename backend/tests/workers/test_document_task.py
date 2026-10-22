# Needed because EagerResult[Any] is not subscriptable at runtime on Celery.
from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Final

import pytest
from celery import Celery, signals
from celery.exceptions import Retry
from celery.result import EagerResult

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.documents.pipeline import PipelineOutcome
from app.llm.mock_provider import HashingEmbeddingProvider, MockLLMProvider
from app.workers.celery_app import (
    DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS,
    DOCUMENT_TASK_TIME_LIMIT_SECONDS,
    PROCESS_DOCUMENT_TASK_NAME,
    celery_app,
)
from app.workers.tasks import DOCUMENT_TASK_MAX_RETRIES, process_document

pytestmark = pytest.mark.integration

_DOCUMENT_ID: Final = uuid.UUID("5b0f8e2a-3c71-4d9e-a6b4-0e2f7d1c9a83")
_UNAVAILABLE: Final = PipelineOutcome.retry("ai_unavailable", None)


@dataclass
class _ScriptedPipeline:
    """Stands in for run_pipeline, giving the scripted outcomes in turn and recording each call.

    An outcome that is an error is raised instead of returned.
    """

    outcomes: list[PipelineOutcome | Exception] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, document_id: uuid.UUID, **arguments: Any) -> PipelineOutcome:
        self.calls.append({"document_id": document_id, **arguments})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def final_attempts(self) -> list[bool]:
        return [call["final_attempt"] for call in self.calls]


@pytest.fixture
def pipeline(integration_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> _ScriptedPipeline:
    """run_pipeline replaced by a script, with the task reading the test's settings.

    Those name the test database, temporary storage and the offline providers.
    """
    scripted = _ScriptedPipeline()
    monkeypatch.setattr("app.workers.tasks.get_settings", lambda: integration_settings)
    monkeypatch.setattr("app.workers.tasks.run_pipeline", scripted)
    return scripted


@pytest.fixture
def requested_retries() -> Iterator[list[Retry]]:
    """Every retry the task asks Celery for while the test runs."""
    retries: list[Retry] = []

    def record(reason: Retry, **_: object) -> None:
        retries.append(reason)

    signals.task_retry.connect(record, weak=False)
    try:
        yield retries
    finally:
        signals.task_retry.disconnect(record)


def _process() -> EagerResult[Any]:
    """Run the task in this process, never through the broker; retries run at once."""
    return process_document.apply(args=(str(_DOCUMENT_ID),))


def _task_lines(output: str) -> list[dict[str, Any]]:
    """The task's own JSON log lines, without those of Celery or the providers."""
    lines = [json.loads(line) for line in output.splitlines() if line.strip()]
    return [line for line in lines if str(line["event"]).startswith("document_processing_")]


def test_the_worker_imports_the_task_module_and_finds_the_document_task() -> None:
    assert "app.workers.tasks" in celery_app.conf.include
    assert PROCESS_DOCUMENT_TASK_NAME in celery_app.tasks


def test_another_celery_app_in_the_same_process_does_not_get_the_document_task() -> None:
    other = Celery("other", set_as_current=False)
    other.finalize()

    assert PROCESS_DOCUMENT_TASK_NAME not in other.tasks
    assert process_document.app is celery_app


def test_the_task_has_the_document_time_limits_and_retry_budget() -> None:
    assert process_document.name == PROCESS_DOCUMENT_TASK_NAME
    assert process_document.max_retries == DOCUMENT_TASK_MAX_RETRIES == 2
    assert process_document.soft_time_limit == DOCUMENT_TASK_SOFT_TIME_LIMIT_SECONDS
    assert process_document.time_limit == DOCUMENT_TASK_TIME_LIMIT_SECONDS


@pytest.mark.parametrize(
    "outcome",
    [
        PipelineOutcome.ready(3),
        PipelineOutcome.failed("pdf_unreadable"),
        PipelineOutcome.skipped("not_claimable"),
    ],
    ids=["ready", "failed", "skipped"],
)
def test_a_run_that_asks_for_no_retry_ends_the_task(
    pipeline: _ScriptedPipeline, outcome: PipelineOutcome
) -> None:
    pipeline.outcomes = [outcome]

    result = _process()

    assert result.successful(), result.traceback
    assert pipeline.final_attempts == [False]
    assert pipeline.calls[0]["document_id"] == _DOCUMENT_ID


def test_the_pipeline_works_with_the_database_storage_and_providers_of_the_settings(
    pipeline: _ScriptedPipeline, integration_settings: Settings
) -> None:
    pipeline.outcomes = [PipelineOutcome.ready(1)]

    _process()

    [call] = pipeline.calls
    assert call["session_factory"] is get_session_factory(integration_settings.database_url)
    expected_path = (integration_settings.storage_dir / "workspace" / "notes.md").resolve()
    assert call["storage"].path_for("workspace/notes.md") == expected_path
    assert isinstance(call["llm"], MockLLMProvider)
    assert isinstance(call["embedder"], HashingEmbeddingProvider)
    assert call["settings"] is integration_settings
    assert call["clock"] is utcnow


def test_an_unavailable_provider_is_tried_again_until_the_final_attempt(
    pipeline: _ScriptedPipeline,
) -> None:
    pipeline.outcomes = [_UNAVAILABLE, _UNAVAILABLE, PipelineOutcome.failed("ai_unavailable")]

    result = _process()

    assert result.successful(), result.traceback
    assert pipeline.final_attempts == [False, False, True]
    assert [call["document_id"] for call in pipeline.calls] == [_DOCUMENT_ID] * 3


def test_a_document_ready_on_a_retry_ends_the_task(pipeline: _ScriptedPipeline) -> None:
    pipeline.outcomes = [_UNAVAILABLE, PipelineOutcome.ready(2)]

    result = _process()

    assert result.successful(), result.traceback
    assert pipeline.final_attempts == [False, False]


def test_each_retry_waits_as_long_as_the_retry_policy_says(
    pipeline: _ScriptedPipeline, requested_retries: list[Retry]
) -> None:
    pipeline.outcomes = [
        _UNAVAILABLE,
        PipelineOutcome.retry("ai_unavailable", 200.0),
        PipelineOutcome.failed("ai_unavailable"),
    ]

    _process()

    # The first retry waits the shortest backoff; the second as long as the provider asked.
    assert [retry.when for retry in requested_retries] == [30, 200.0]


def test_an_error_that_escapes_the_pipeline_fails_the_task_without_a_retry(
    pipeline: _ScriptedPipeline,
) -> None:
    pipeline.outcomes = [ConnectionError("the database is unreachable"), PipelineOutcome.ready(1)]

    result = _process()

    assert result.failed()
    assert isinstance(result.result, ConnectionError)
    assert pipeline.final_attempts == [False]


def test_a_run_is_logged_with_its_document_outcome_duration_and_chunk_count(
    pipeline: _ScriptedPipeline, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", "json")
    pipeline.outcomes = [PipelineOutcome.ready(4)]

    _process()

    started, finished = _task_lines(capsys.readouterr().out)
    assert started["event"] == "document_processing_started"
    assert started["attempt"] == 1
    assert finished["event"] == "document_processing_finished"
    assert finished["outcome"] == "ready"
    assert finished["chunk_count"] == 4
    assert finished["duration_ms"] >= 0
    assert started["document_id"] == finished["document_id"] == str(_DOCUMENT_ID)


def test_a_failed_document_is_logged_as_a_warning_with_its_error_code(
    pipeline: _ScriptedPipeline, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", "json")
    pipeline.outcomes = [PipelineOutcome.failed("pdf_unreadable")]

    _process()

    lines = _task_lines(capsys.readouterr().out)
    assert [line["event"] for line in lines] == [
        "document_processing_started",
        "document_processing_finished",
        "document_processing_failed",
    ]
    failed = lines[-1]
    assert failed["code"] == "pdf_unreadable"
    assert failed["level"] == "warning"
    assert failed["document_id"] == str(_DOCUMENT_ID)


def test_every_attempt_is_logged_with_its_number_and_outcome(
    pipeline: _ScriptedPipeline, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", "json")
    pipeline.outcomes = [_UNAVAILABLE, PipelineOutcome.ready(1)]

    _process()

    lines = _task_lines(capsys.readouterr().out)
    started = [line for line in lines if line["event"] == "document_processing_started"]
    finished = [line for line in lines if line["event"] == "document_processing_finished"]
    assert [line["attempt"] for line in started] == [1, 2]
    assert [line["outcome"] for line in finished] == ["retry", "ready"]
