import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog

from app.core.logging import configure_logging


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_json_lines_carry_event_fields_level_and_timestamp(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")

    structlog.get_logger("test").info("document_uploaded", size_bytes=2048)

    [line] = _json_lines(capsys.readouterr().out)
    assert line["event"] == "document_uploaded"
    assert line["size_bytes"] == 2048
    assert line["level"] == "info"
    assert "timestamp" in line


def test_bound_context_variables_are_added_to_every_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    structlog.contextvars.bind_contextvars(request_id="req-12345678")

    structlog.get_logger("test").info("first")
    structlog.get_logger("test").warning("second")

    lines = _json_lines(capsys.readouterr().out)
    assert [line["request_id"] for line in lines] == ["req-12345678", "req-12345678"]


def test_standard_library_loggers_use_the_same_format(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")

    logging.getLogger("third.party").warning("disk at %s%%", 91)

    [line] = _json_lines(capsys.readouterr().out)
    assert line["event"] == "disk at 91%"
    assert line["logger"] == "third.party"


def test_exceptions_are_rendered_as_structured_data(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")

    try:
        raise ValueError("broken chunk")
    except ValueError:
        structlog.get_logger("test").exception("chunking_failed")

    [line] = _json_lines(capsys.readouterr().out)
    assert line["exception"][0]["exc_type"] == "ValueError"
    assert line["exception"][0]["exc_value"] == "broken chunk"


def test_messages_below_the_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", "json")

    structlog.get_logger("test").info("hidden")

    assert capsys.readouterr().out == ""


def test_console_format_is_human_readable(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "console")

    structlog.get_logger("test").info("worker_started", concurrency=2)

    output = capsys.readouterr().out
    assert "worker_started" in output
    assert "concurrency" in output


def test_uvicorn_loggers_follow_the_configured_level(capsys: pytest.CaptureFixture[str]) -> None:
    # uvicorn's own dictConfig sets this level before configure_logging runs.
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    configure_logging("WARNING", "json")

    logging.getLogger("uvicorn.error").info("startup noise")
    logging.getLogger("uvicorn.error").warning("port busy")

    [line] = _json_lines(capsys.readouterr().out)
    assert line["event"] == "port busy"


def test_http_client_request_lines_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")

    logging.getLogger("httpx2").info('HTTP Request: POST https://llm.test/v1 "HTTP/1.1 200 OK"')
    logging.getLogger("httpx2").warning("connection pool is full")

    lines = _json_lines(capsys.readouterr().out)
    assert [line["event"] for line in lines] == ["connection pool is full"]


def test_pdf_parser_warnings_are_dropped_but_its_errors_are_kept(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")

    logging.getLogger("pypdf._reader").warning("Ignoring wrong pointing object 6 0 (offset 0)")
    logging.getLogger("pypdf._reader").error("Invalid stream length")

    lines = _json_lines(capsys.readouterr().out)
    assert [line["event"] for line in lines] == ["Invalid stream length"]


def test_quieted_libraries_never_log_below_the_configured_level(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("ERROR", "json")

    logging.getLogger("httpx2").warning("connection pool is full")

    assert capsys.readouterr().out == ""


def _raise_with_local_secret() -> None:
    password = "hunter2-local-secret"
    if password:
        raise ValueError("connection failed")


def test_exception_locals_are_not_leaked_into_json_logs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")

    try:
        _raise_with_local_secret()
    except ValueError:
        structlog.get_logger("test").exception("db_connect_failed")

    output = capsys.readouterr().out
    assert "hunter2-local-secret" not in output
    [line] = _json_lines(output)
    assert line["exception"][0]["exc_type"] == "ValueError"
    assert line["exception"][0]["exc_value"] == "connection failed"
