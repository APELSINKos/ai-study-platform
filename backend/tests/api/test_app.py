from fastapi.testclient import TestClient

from app import __version__

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
