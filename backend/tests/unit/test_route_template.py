from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from app.core.middleware import RequestContextMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    health_router = APIRouter(prefix="/health")

    @health_router.get("/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    api_router = APIRouter()
    api_router.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/direct")
    def direct() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_route_template_keeps_the_prefixes_of_nested_routers() -> None:
    with TestClient(_build_app()) as client:
        client.get("/api/v1/health/live")
        client.get("/direct")

    metrics = generate_latest().decode()

    assert 'route="/api/v1/health/live"' in metrics
    assert 'route="/direct"' in metrics
