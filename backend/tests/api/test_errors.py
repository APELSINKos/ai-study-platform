from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.schemas.errors import ErrorDetail

MIN_TITLE_LENGTH = 3


class _Item(BaseModel):
    title: str = Field(min_length=MIN_TITLE_LENGTH)
    count: int


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    @app.get("/test/not-found")
    def not_found() -> None:
        raise NotFoundError("Workspace not found.", code="workspace_not_found")

    @app.get("/test/conflict")
    def conflict() -> None:
        raise ConflictError(details=[ErrorDetail(field="name", message="Already taken.")])

    @app.get("/test/throttled")
    def throttled() -> None:
        raise AppError("Slow down.", code="rate_limited", headers={"Retry-After": "5"})

    @app.post("/test/items")
    def create_item(item: _Item) -> _Item:
        return item

    with TestClient(app) as test_client:
        yield test_client


def test_app_error_uses_the_unified_shape(client: TestClient) -> None:
    response = client.get("/test/not-found")

    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "workspace_not_found"
    assert body["message"] == "Workspace not found."
    assert body["details"] == []
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_app_error_subclass_falls_back_to_its_defaults(client: TestClient) -> None:
    response = client.get("/test/conflict")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "conflict"
    assert error["message"] == ConflictError.message
    assert error["details"] == [{"field": "name", "message": "Already taken."}]


def test_app_error_headers_are_sent(client: TestClient) -> None:
    response = client.get("/test/throttled")

    assert response.status_code == 400
    assert response.headers["retry-after"] == "5"


def test_validation_errors_list_every_invalid_field(client: TestClient) -> None:
    response = client.post("/test/items", json={"title": "ab"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {detail["field"] for detail in error["details"]} == {"title", "count"}


def test_unknown_route_returns_not_found_in_the_unified_shape(client: TestClient) -> None:
    response = client.get("/definitely/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_wrong_method_returns_method_not_allowed(client: TestClient) -> None:
    response = client.delete("/test/items")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
