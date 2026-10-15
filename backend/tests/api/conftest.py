import uuid
from collections.abc import Iterator
from http import HTTPStatus
from typing import Final, NamedTuple

import httpx2
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session

from app.api.cookies import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.api.deps import CurrentUser, get_db, get_document_queue
from app.core.config import Settings
from app.core.redis import get_redis_client
from app.core.request_context import get_request_id
from app.documents.queue import QueueUnavailableError
from app.main import create_app

PASSWORD: Final = "correct horse battery staple"
_REGISTER_PATH: Final = "/api/v1/auth/register"

# A route with no purpose other than exercising CurrentUser's CSRF enforcement on a
# mutating request; production code has no such endpoint yet at this stage.
_csrf_probe_router = APIRouter()


@_csrf_probe_router.post("/api/v1/_test/protected")
def _csrf_probe(current_user: CurrentUser) -> dict[str, str]:
    return {"user_id": str(current_user.id)}


def register(
    client: TestClient, *, email: str, password: str = PASSWORD, display_name: str = "Person"
) -> httpx2.Response:
    """Create an account; on success the client's cookie jar holds the new session."""
    return client.post(
        _REGISTER_PATH, json={"email": email, "password": password, "display_name": display_name}
    )


def csrf_headers(client: TestClient) -> dict[str, str]:
    """The header a cookie-authenticated unsafe request needs, read from the client's cookie."""
    token = client.cookies.get(CSRF_COOKIE_NAME)
    assert token is not None
    return {CSRF_HEADER_NAME: token}


def _sign_up(client: TestClient, email: str) -> None:
    response = register(client, email=email)
    assert response.status_code == HTTPStatus.CREATED


class QueuedDocument(NamedTuple):
    document_id: uuid.UUID
    # The id of the API request that queued the document, which the worker logs with it.
    request_id: str | None


class RecordingDocumentQueue:
    """Stands in for the broker: remembers what was queued, or fails like a broker that is down."""

    def __init__(self) -> None:
        self.enqueued: list[QueuedDocument] = []
        self.unavailable = False

    def enqueue(self, document_id: uuid.UUID) -> None:
        if self.unavailable:
            raise QueueUnavailableError("The broker is not reachable.")
        self.enqueued.append(QueuedDocument(document_id, get_request_id()))


@pytest.fixture
def document_queue() -> RecordingDocumentQueue:
    return RecordingDocumentQueue()


@pytest.fixture
def auth_app(
    integration_settings: Settings, db_session: Session, document_queue: RecordingDocumentQueue
) -> FastAPI:
    app = create_app(integration_settings)
    app.dependency_overrides[get_db] = lambda: db_session
    # Tests never publish to a real broker.
    app.dependency_overrides[get_document_queue] = lambda: document_queue
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


@pytest.fixture
def user_client(auth_client: TestClient) -> TestClient:
    """auth_client, signed in with cookies as a newly registered user."""
    _sign_up(auth_client, "user@example.com")
    return auth_client


@pytest.fixture
def other_user_client(auth_app: FastAPI, auth_redis: Redis) -> Iterator[TestClient]:
    """A second client of the same app, signed in as a different user."""
    with TestClient(auth_app) as test_client:
        _sign_up(test_client, "other-user@example.com")
        yield test_client
