import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app import __version__
from app.api.v1.router import api_router
from app.core.logging import configure_logging

FRONTEND_ORIGIN = "http://localhost:3000"


def test_openapi_schema_names_the_api(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    info = response.json()["info"]
    assert info["title"] == "AI Study Platform"
    assert info["version"] == __version__


def test_cors_allows_the_configured_origin_with_credentials(client: TestClient) -> None:
    response = client.options(
        "/openapi.json",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_ignores_unknown_origins(client: TestClient) -> None:
    response = client.options(
        "/openapi.json",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_metrics_requests_are_not_logged_at_info(
    capsys: pytest.CaptureFixture[str], client: TestClient
) -> None:
    configure_logging("INFO", "json")

    client.get("/metrics")

    assert "request_finished" not in capsys.readouterr().out


def test_openapi_documents_the_unified_error_shape_for_validation_errors() -> None:
    original_routes = list(api_router.routes)
    throwaway_router = APIRouter()

    @throwaway_router.get("/test-throwaway")
    def throwaway(value: int) -> dict[str, int]:
        return {"value": value}

    api_router.include_router(throwaway_router)
    try:
        test_app = FastAPI()
        test_app.include_router(api_router, prefix="/api/v1")
        schema = test_app.openapi()
    finally:
        api_router.routes = original_routes

    schemas = schema["components"]["schemas"]
    assert "ErrorResponse" in schemas
    assert "HTTPValidationError" not in schemas
