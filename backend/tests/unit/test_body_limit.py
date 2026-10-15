import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from http import HTTPStatus
from typing import Final

import httpx2
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.cookies import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.api.deps import get_db, get_redis
from app.api.errors import register_exception_handlers
from app.core.body_limit import (
    MAX_REQUEST_BODY_BYTES,
    MULTIPART_OVERHEAD_BYTES,
    RequestBodyLimitMiddleware,
)
from app.core.clock import utcnow
from app.core.config import MIB, Settings
from app.core.middleware import REQUEST_ID_HEADER
from app.core.security import create_access_token
from app.main import UPLOAD_PATH
from tests.conftest import FRONTEND_ORIGIN

_UPLOAD_ROUTE: Final = "/api/v1/workspaces/{workspace_id}/documents"
_TOKEN_PATH: Final = "/api/v1/auth/token"
_ECHO_PATH: Final = "/test/echo"
_CHUNK: Final = b"x" * (64 * 1024)
_BOUNDARY: Final = "body-limit-test-boundary"
_CSRF_TOKEN: Final = "csrf-token-of-the-signed-in-session"


class _BodyReadCounter:
    """Wraps an app and counts the request body messages it pulls from the server."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.chunks_read = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def counting_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                self.chunks_read += 1
            return message

        await self.app(scope, counting_receive, send)


def _no_backend() -> None:
    raise AssertionError("the request reached a route that uses the database or Redis")


def _upload_url() -> str:
    return _UPLOAD_ROUTE.format(workspace_id=uuid.uuid4())


def _upload_cap(settings: Settings) -> int:
    return settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES


def _access_token(settings: Settings, *, ttl: timedelta = timedelta(minutes=15)) -> str:
    secret = settings.secret_key.get_secret_value()
    return create_access_token(uuid.uuid4(), secret=secret, ttl=ttl, now=utcnow()).value


def _bearer(settings: Settings, *, ttl: timedelta = timedelta(minutes=15)) -> dict[str, str]:
    return {"Authorization": f"Bearer {_access_token(settings, ttl=ttl)}"}


def _file(size: int) -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("notes.txt", b"x" * size, "text/plain")}


def _multipart(file_size: int) -> tuple[bytes, str]:
    """A form with one file of the given size, and the Content-Type that describes it."""
    head = (
        f"--{_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="file"; filename="notes.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    )
    body = head.encode() + b"x" * file_size + f"\r\n--{_BOUNDARY}--\r\n".encode()
    return body, f"multipart/form-data; boundary={_BOUNDARY}"


def _in_chunks(body: bytes) -> Iterator[bytes]:
    """A generator body, which the client sends chunked, without a Content-Length."""
    for start in range(0, len(body), len(_CHUNK)):
        yield body[start : start + len(_CHUNK)]


def _limited_app(settings: Settings) -> FastAPI:
    """The limiter alone, in front of stand-ins for the upload and document-list routes."""
    limited = FastAPI()
    register_exception_handlers(limited)
    limited.add_middleware(RequestBodyLimitMiddleware, settings=settings, upload_path=UPLOAD_PATH)

    @limited.post(_UPLOAD_ROUTE)
    async def upload(request: Request) -> dict[str, int]:
        return {"received": len(await request.body())}

    @limited.get(_UPLOAD_ROUTE)
    def list_documents() -> dict[str, str]:
        return {"status": "listed"}

    return limited


@pytest.fixture
def counted_app(app: FastAPI) -> _BodyReadCounter:
    """The real application, with an extra route that reads its body, behind a counter.

    Its routes cannot reach the database or Redis: these tests run without either.
    """
    app.dependency_overrides[get_db] = _no_backend
    app.dependency_overrides[get_redis] = _no_backend

    @app.post(_ECHO_PATH)
    async def echo(request: Request) -> dict[str, int]:
        return {"received": len(await request.body())}

    return _BodyReadCounter(app)


@pytest.fixture
def client(counted_app: _BodyReadCounter) -> Iterator[TestClient]:
    with TestClient(counted_app, headers={"Origin": FRONTEND_ORIGIN}) as test_client:
        yield test_client


@pytest.fixture
def limited_client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(_limited_app(settings)) as test_client:
        yield test_client


def _assert_refused_unread(
    response: httpx2.Response, counted_app: _BodyReadCounter, status: HTTPStatus, code: str
) -> None:
    """The unified error, with CORS and request-id headers, sent before any body was read."""
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert counted_app.chunks_read == 0


# --- the upload route -----------------------------------------------------------


def test_an_upload_declaring_more_than_its_cap_is_refused_before_it_is_read(
    client: TestClient, counted_app: _BodyReadCounter, settings: Settings
) -> None:
    body = b"x" * (_upload_cap(settings) + 1)

    response = client.post(_upload_url(), content=body, headers=_bearer(settings))

    _assert_refused_unread(response, counted_app, HTTPStatus.CONTENT_TOO_LARGE, "payload_too_large")


def test_an_upload_without_credentials_is_refused_before_it_is_read(
    client: TestClient, counted_app: _BodyReadCounter
) -> None:
    response = client.post(_upload_url(), files=_file(3 * MIB))

    _assert_refused_unread(response, counted_app, HTTPStatus.UNAUTHORIZED, "not_authenticated")
    assert response.headers["www-authenticate"] == "Bearer"


def test_an_upload_with_a_dummy_bearer_token_is_refused_before_it_is_read(
    client: TestClient, counted_app: _BodyReadCounter
) -> None:
    response = client.post(
        _upload_url(), files=_file(3 * MIB), headers={"Authorization": "Bearer x"}
    )

    _assert_refused_unread(response, counted_app, HTTPStatus.UNAUTHORIZED, "invalid_token")
    assert response.headers["www-authenticate"] == "Bearer"


def test_an_upload_with_an_expired_token_is_refused_before_it_is_read(
    client: TestClient, counted_app: _BodyReadCounter, settings: Settings
) -> None:
    expired = _bearer(settings, ttl=timedelta(seconds=-1))

    response = client.post(_upload_url(), files=_file(3 * MIB), headers=expired)

    _assert_refused_unread(response, counted_app, HTTPStatus.UNAUTHORIZED, "token_expired")
    assert response.headers["www-authenticate"] == "Bearer"


def test_an_anonymous_upload_over_its_cap_is_refused_as_unauthenticated(
    client: TestClient, counted_app: _BodyReadCounter, settings: Settings
) -> None:
    body = b"x" * (_upload_cap(settings) + 1)

    response = client.post(_upload_url(), content=body)

    _assert_refused_unread(response, counted_app, HTTPStatus.UNAUTHORIZED, "not_authenticated")


def test_a_cookie_upload_without_the_csrf_header_is_refused_before_it_is_read(
    client: TestClient, counted_app: _BodyReadCounter, settings: Settings
) -> None:
    client.cookies.set(ACCESS_COOKIE_NAME, _access_token(settings))
    client.cookies.set(CSRF_COOKIE_NAME, _CSRF_TOKEN)

    response = client.post(_upload_url(), files=_file(3 * MIB))

    _assert_refused_unread(response, counted_app, HTTPStatus.FORBIDDEN, "csrf_failed")


def test_an_authenticated_upload_of_exactly_its_cap_reaches_the_route_in_full(
    limited_client: TestClient, settings: Settings
) -> None:
    cap = _upload_cap(settings)

    response = limited_client.post(_upload_url(), content=b"x" * cap, headers=_bearer(settings))

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"received": cap}


def test_a_cookie_upload_with_the_csrf_header_reaches_the_route(
    limited_client: TestClient, settings: Settings
) -> None:
    limited_client.cookies.set(ACCESS_COOKIE_NAME, _access_token(settings))
    limited_client.cookies.set(CSRF_COOKIE_NAME, _CSRF_TOKEN)

    response = limited_client.post(
        _upload_url(), content=b"notes", headers={CSRF_HEADER_NAME: _CSRF_TOKEN}
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"received": len(b"notes")}


def test_a_streamed_upload_is_cut_off_at_the_first_chunk_past_its_cap(
    settings: Settings,
) -> None:
    cap = _upload_cap(settings)
    chunks_sent = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal chunks_sent
        for _ in range(cap // len(_CHUNK) + 10):
            chunks_sent += 1
            yield _CHUNK

    async def upload() -> httpx2.Response:
        transport = httpx2.ASGITransport(app=_limited_app(settings))
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(_upload_url(), content=body(), headers=_bearer(settings))

    response = asyncio.run(upload())

    assert response.status_code == HTTPStatus.CONTENT_TOO_LARGE
    assert response.json()["error"]["code"] == "payload_too_large"
    assert chunks_sent == cap // len(_CHUNK) + 1


def test_listing_documents_is_left_for_the_route_to_authenticate(
    limited_client: TestClient,
) -> None:
    response = limited_client.get(_upload_url())

    assert response.status_code == HTTPStatus.OK


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/workspaces",
        "/api/v1/workspaces/3f6c1c1e-8c5e-4a8e-9a43-2a4bb3c51a7e",
        "/api/v1/workspaces/3f6c1c1e-8c5e-4a8e-9a43-2a4bb3c51a7e/documents/",
        "/api/v1/workspaces/3f6c1c1e-8c5e-4a8e-9a43-2a4bb3c51a7e/documents/extra",
        "/api/v1/workspaces/a/b/documents",
        "/api/v2/workspaces/3f6c1c1e-8c5e-4a8e-9a43-2a4bb3c51a7e/documents",
    ],
)
def test_no_other_path_counts_as_the_upload_route(path: str) -> None:
    assert UPLOAD_PATH.fullmatch(path) is None


# --- every other route --------------------------------------------------------


def test_a_2_mib_multipart_to_the_token_route_is_refused_before_it_is_read(
    client: TestClient, counted_app: _BodyReadCounter
) -> None:
    response = client.post(
        _TOKEN_PATH,
        data={"username": "user@example.com", "password": "correct horse battery staple"},
        files=_file(2 * MIB),
    )

    _assert_refused_unread(response, counted_app, HTTPStatus.CONTENT_TOO_LARGE, "payload_too_large")


def test_a_chunked_body_over_the_cap_is_refused_with_the_unified_error(
    client: TestClient,
) -> None:
    body, content_type = _multipart(2 * MIB)

    response = client.post(
        _TOKEN_PATH, content=_in_chunks(body), headers={"Content-Type": content_type}
    )

    assert "content-length" not in response.request.headers
    assert response.status_code == HTTPStatus.CONTENT_TOO_LARGE
    error = response.json()["error"]
    assert error["code"] == "payload_too_large"
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_one_byte_over_the_global_cap_is_refused_before_it_is_read(
    client: TestClient, counted_app: _BodyReadCounter
) -> None:
    response = client.post(_ECHO_PATH, content=b"x" * (MAX_REQUEST_BODY_BYTES + 1))

    _assert_refused_unread(response, counted_app, HTTPStatus.CONTENT_TOO_LARGE, "payload_too_large")


def test_other_routes_take_up_to_the_global_cap_and_no_early_credentials(
    client: TestClient,
) -> None:
    response = client.post(_ECHO_PATH, content=b"x" * MAX_REQUEST_BODY_BYTES)

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"received": MAX_REQUEST_BODY_BYTES}


@pytest.mark.parametrize("content_length", ["abc", "9" * 5000])
def test_an_unreadable_content_length_is_left_to_the_running_count(
    client: TestClient, content_length: str
) -> None:
    response = client.post(_ECHO_PATH, content=b"notes", headers={"Content-Length": content_length})

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"received": len(b"notes")}
