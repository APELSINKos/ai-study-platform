from collections.abc import Iterator

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db
from app.core.config import Settings
from app.core.redis import get_redis_client
from app.main import create_app

# A route with no purpose other than exercising CurrentUser's CSRF enforcement on a
# mutating request; production code has no such endpoint yet at this stage.
_csrf_probe_router = APIRouter()


@_csrf_probe_router.post("/api/v1/_test/protected")
def _csrf_probe(current_user: CurrentUser) -> dict[str, str]:
    return {"user_id": str(current_user.id)}


@pytest.fixture
def auth_app(integration_settings: Settings, db_session: Session) -> FastAPI:
    app = create_app(integration_settings)
    app.dependency_overrides[get_db] = lambda: db_session
    app.include_router(_csrf_probe_router)
    return app


@pytest.fixture
def auth_redis(integration_settings: Settings) -> Iterator[Redis]:
    client = get_redis_client(integration_settings.redis_url)
    client.flushdb()
    yield client
    client.flushdb()


@pytest.fixture
def auth_client(auth_app: FastAPI, auth_redis: Redis) -> Iterator[TestClient]:
    with TestClient(auth_app) as test_client:
        yield test_client
