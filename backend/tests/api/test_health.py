import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.api.deps import get_db, get_redis
from app.core.logging import configure_logging

SECRET_IN_ERROR = "password=hunter2"


class _Session:
    def __init__(self, *, broken: bool) -> None:
        self.broken = broken

    def execute(self, statement: object) -> None:
        if self.broken:
            raise OperationalError(
                "SELECT 1", {}, Exception(f"connection refused {SECRET_IN_ERROR}")
            )


class _Redis:
    def __init__(self, *, broken: bool) -> None:
        self.broken = broken

    def ping(self) -> bool:
        if self.broken:
            raise RedisConnectionError(f"Connection refused {SECRET_IN_ERROR}")
        return True


def _use_backends(app: FastAPI, *, database_down: bool, redis_down: bool) -> None:
    app.dependency_overrides[get_db] = lambda: _Session(broken=database_down)
    app.dependency_overrides[get_redis] = lambda: _Redis(broken=redis_down)


def test_liveness_does_not_touch_dependencies(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_is_ok_when_every_dependency_answers(app: FastAPI, client: TestClient) -> None:
    _use_backends(app, database_down=False, redis_down=False)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {name: check["status"] for name, check in body["checks"].items()} == {
        "database": "ok",
        "redis": "ok",
    }
    assert all(check["latency_ms"] >= 0 for check in body["checks"].values())


@pytest.mark.parametrize(
    ("database_down", "redis_down"),
    [(True, False), (False, True), (True, True)],
)
def test_readiness_reports_each_failed_dependency_without_leaking_details(
    app: FastAPI, client: TestClient, database_down: bool, redis_down: bool
) -> None:
    _use_backends(app, database_down=database_down, redis_down=redis_down)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"]["status"] == ("error" if database_down else "ok")
    assert body["checks"]["redis"]["status"] == ("error" if redis_down else "ok")
    assert SECRET_IN_ERROR not in response.text
    assert client.get("/api/v1/health/live").status_code == 200


def test_health_probes_are_not_logged_at_info(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", "json")

    client.get("/api/v1/health/live")

    events = [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines() if line]
    assert "request_finished" not in events
