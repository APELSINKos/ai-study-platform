import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware

GENERATED_ID = re.compile(r"[0-9a-f]{32}")
LEAKED_SECRET = "postgres password is hunter2"  # noqa: S105 -- fixture value, not a real secret


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    @app.get("/test/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/test/crash")
    def crash() -> None:
        raise RuntimeError(LEAKED_SECRET)

    with TestClient(app) as test_client:
        yield test_client


def _log_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_a_request_id_is_generated_when_the_client_sends_none(client: TestClient) -> None:
    response = client.get("/test/ok")

    assert GENERATED_ID.fullmatch(response.headers[REQUEST_ID_HEADER])


def test_a_valid_incoming_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/test/ok", headers={REQUEST_ID_HEADER: "web-3f2a.91_b"})

    assert response.headers[REQUEST_ID_HEADER] == "web-3f2a.91_b"


@pytest.mark.parametrize(
    "incoming",
    ["short1", "x" * 65, "has spaces 123", "semi;colon;123", "slash/inside/1"],
)
def test_an_invalid_incoming_request_id_is_replaced(client: TestClient, incoming: str) -> None:
    response = client.get("/test/ok", headers={REQUEST_ID_HEADER: incoming})

    assert GENERATED_ID.fullmatch(response.headers[REQUEST_ID_HEADER])


def test_error_bodies_carry_the_same_request_id_as_the_header(client: TestClient) -> None:
    response = client.get("/definitely/missing")

    assert response.json()["error"]["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_unhandled_exceptions_become_generic_json_500s(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    response = client.get("/test/crash")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert LEAKED_SECRET not in response.text
    events = [line["event"] for line in _log_lines(capsys.readouterr().out)]
    assert "unhandled_exception" in events


def test_each_request_is_logged_once_with_its_outcome(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()

    response = client.get("/test/ok", headers={REQUEST_ID_HEADER: "trace-0001"})

    [line] = [
        line for line in _log_lines(capsys.readouterr().out) if line["event"] == "request_finished"
    ]
    assert line["request_id"] == "trace-0001"
    assert line["method"] == "GET"
    assert line["route"] == "/test/ok"
    assert line["status"] == response.status_code
    assert line["duration_ms"] >= 0


def test_quiet_paths_are_logged_below_info(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")
    quiet_app = FastAPI()
    quiet_app.add_middleware(RequestContextMiddleware, quiet_paths=frozenset({"/ping"}))

    @quiet_app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(quiet_app) as quiet_client:
        quiet_client.get("/ping")

    assert "request_finished" not in capsys.readouterr().out
