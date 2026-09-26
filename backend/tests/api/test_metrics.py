from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app

TOKEN = "scrape-token-for-tests"  # noqa: S105 -- dummy token used only in these tests


def _client(**overrides: object) -> TestClient:
    values: dict[str, object] = {"environment": "test", **overrides}
    return TestClient(create_app(Settings.model_validate(values)))


def test_metrics_are_open_in_development_without_a_token(client: TestClient) -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text


def test_requests_are_labelled_by_route_template(client: TestClient) -> None:
    client.get("/api/v1/health/live")

    assert 'route="/api/v1/health/live"' in client.get("/metrics").text


def test_unknown_paths_share_one_label(client: TestClient) -> None:
    client.get("/wp-admin/12345")

    metrics = client.get("/metrics").text
    assert 'route="unmatched"' in metrics
    assert "wp-admin" not in metrics


def test_a_configured_token_is_required() -> None:
    with _client(metrics_token=SecretStr(TOKEN)) as secured:
        missing = secured.get("/metrics")
        wrong = secured.get("/metrics", headers={"Authorization": "Bearer nope"})
        right = secured.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert missing.json()["error"]["code"] == "not_authenticated"
    assert wrong.status_code == 401
    assert right.status_code == 200


def test_metrics_are_hidden_in_production_without_a_token() -> None:
    with _client(environment="production") as production:
        response = production.get("/metrics")

    assert response.status_code == 404


def test_metrics_endpoint_is_not_part_of_the_public_api(client: TestClient) -> None:
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def test_unusual_methods_share_one_label(client: TestClient) -> None:
    client.request("BREW", "/api/v1/health/live")

    metrics = client.get("/metrics").text
    assert 'method="OTHER"' in metrics
    assert "BREW" not in metrics
