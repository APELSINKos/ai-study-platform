import time
from http import HTTPStatus
from typing import Final

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.cookies import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    CSRF_COOKIE_PATH,
    CSRF_HEADER_NAME,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
)
from app.api.deps import get_redis
from app.core.config import Settings
from app.models.refresh_token import RefreshToken

pytestmark = pytest.mark.integration

_PASSWORD: Final = "correct horse battery staple"  # noqa: S105 -- test fixture, not a secret
_REGISTER_PATH: Final = "/api/v1/auth/register"
_LOGIN_PATH: Final = "/api/v1/auth/login"
_TOKEN_PATH: Final = "/api/v1/auth/token"  # noqa: S105 -- a URL path, not a credential
_REFRESH_PATH: Final = "/api/v1/auth/refresh"
_LOGOUT_PATH: Final = "/api/v1/auth/logout"
_ME_PATH: Final = "/api/v1/auth/me"
_PROTECTED_PATH: Final = "/api/v1/_test/protected"


def _register(
    client: TestClient, *, email: str, password: str = _PASSWORD, display_name: str = "Person"
) -> httpx2.Response:
    return client.post(
        _REGISTER_PATH, json={"email": email, "password": password, "display_name": display_name}
    )


def _login(client: TestClient, *, email: str, password: str = _PASSWORD) -> httpx2.Response:
    return client.post(_LOGIN_PATH, json={"email": email, "password": password})


def _set_cookie_header(response: httpx2.Response, name: str) -> str:
    [value] = [
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith(f"{name}=")
    ]
    return value


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE_NAME)
    assert token is not None
    return {CSRF_HEADER_NAME: token}


def _replay_refresh(app: FastAPI, *, refresh_token: str, csrf_token: str) -> httpx2.Response:
    """A second, cookie-jar-free client replaying a captured refresh/CSRF cookie pair."""
    with TestClient(app) as client:
        client.cookies.set(REFRESH_COOKIE_NAME, refresh_token, path=REFRESH_COOKIE_PATH)
        client.cookies.set(CSRF_COOKIE_NAME, csrf_token, path=CSRF_COOKIE_PATH)
        return client.post(_REFRESH_PATH, headers={CSRF_HEADER_NAME: csrf_token})


class _BrokenPipeline:
    """A Redis pipeline that always fails, as if the connection were down."""

    def __enter__(self) -> "_BrokenPipeline":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def incr(self, key: str) -> "_BrokenPipeline":
        return self

    def expire(self, key: str, seconds: int, *, nx: bool = False) -> "_BrokenPipeline":
        return self

    def execute(self) -> tuple[int, bool]:
        raise RedisConnectionError("connection refused")


class _BrokenRedis:
    def pipeline(self) -> _BrokenPipeline:
        return _BrokenPipeline()


# --- register -------------------------------------------------------------------


def test_register_returns_a_session_and_sets_the_three_cookies(auth_client: TestClient) -> None:
    response = _register(auth_client, email="new-user@example.com")

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["user"]["email"] == "new-user@example.com"
    assert body["user"]["display_name"] == "Person"
    assert "password" not in body["user"]
    assert "password_hash" not in str(body)
    assert body["token_type"] == "bearer"  # noqa: S105 -- a token kind label, not a credential
    assert body["expires_in"] > 0

    access = _set_cookie_header(response, ACCESS_COOKIE_NAME).lower()
    refresh = _set_cookie_header(response, REFRESH_COOKIE_NAME).lower()
    csrf = _set_cookie_header(response, CSRF_COOKIE_NAME).lower()

    assert "httponly" in access
    assert "samesite=lax" in access
    assert "path=/api" in access
    assert "path=/api/v1/auth" not in access

    assert "httponly" in refresh
    assert "samesite=strict" in refresh
    assert "path=/api/v1/auth" in refresh

    assert "httponly" not in csrf
    assert "samesite=lax" in csrf
    assert "path=/" in csrf


def test_register_rejects_a_duplicate_email_with_409(auth_client: TestClient) -> None:
    _register(auth_client, email="dupe@example.com")

    response = _register(auth_client, email="Dupe@Example.com")

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["error"]["code"] == "email_taken"


def test_register_rejects_invalid_input_with_the_unified_error_shape(
    auth_client: TestClient,
) -> None:
    response = auth_client.post(
        _REGISTER_PATH, json={"email": "not-an-email", "password": "short", "display_name": ""}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    body = response.json()
    fields = {detail["field"] for detail in body["error"]["details"]}
    assert {"email", "password", "display_name"} <= fields


# --- login ------------------------------------------------------------------------


def test_login_with_correct_credentials_returns_a_session(auth_client: TestClient) -> None:
    _register(auth_client, email="login-ok@example.com")

    response = _login(auth_client, email="login-ok@example.com")

    assert response.status_code == HTTPStatus.OK
    assert response.json()["user"]["email"] == "login-ok@example.com"


def test_login_unknown_email_and_wrong_password_return_identical_bodies(
    auth_client: TestClient,
) -> None:
    _register(auth_client, email="known@example.com")

    unknown = _login(auth_client, email="unknown@example.com")
    wrong = _login(auth_client, email="known@example.com", password="not-the-password")  # noqa: S106

    assert unknown.status_code == HTTPStatus.UNAUTHORIZED
    assert wrong.status_code == HTTPStatus.UNAUTHORIZED
    assert unknown.headers["www-authenticate"] == "Bearer"
    assert wrong.headers["www-authenticate"] == "Bearer"
    unknown_error = unknown.json()["error"]
    wrong_error = wrong.json()["error"]
    del unknown_error["request_id"]
    del wrong_error["request_id"]
    assert unknown_error == wrong_error


def test_the_eleventh_login_attempt_for_one_ip_and_email_is_rate_limited(
    auth_client: TestClient, integration_settings: Settings
) -> None:
    _register(auth_client, email="throttled@example.com")

    for _ in range(integration_settings.login_attempts_per_minute):
        response = _login(auth_client, email="throttled@example.com", password="wrong")  # noqa: S106
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    response = _login(auth_client, email="throttled@example.com", password="wrong")  # noqa: S106

    assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert int(response.headers["retry-after"]) > 0
    assert response.json()["error"]["code"] == "rate_limited"


def test_login_still_works_when_redis_is_unreachable(
    auth_app: FastAPI, auth_client: TestClient
) -> None:
    _register(auth_client, email="resilient@example.com")
    auth_app.dependency_overrides[get_redis] = _BrokenRedis

    response = _login(auth_client, email="resilient@example.com")

    assert response.status_code == HTTPStatus.OK


# --- me -----------------------------------------------------------------------


def test_me_via_bearer_token(auth_client: TestClient) -> None:
    registered = _register(auth_client, email="bearer-me@example.com").json()

    response = auth_client.get(
        _ME_PATH, headers={"Authorization": f"Bearer {registered['access_token']}"}
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["email"] == "bearer-me@example.com"


def test_me_via_cookie(auth_client: TestClient) -> None:
    _register(auth_client, email="cookie-me@example.com")

    response = auth_client.get(_ME_PATH)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["email"] == "cookie-me@example.com"


# --- CSRF -----------------------------------------------------------------------


def test_cookie_authenticated_post_without_csrf_header_is_rejected(
    auth_client: TestClient,
) -> None:
    _register(auth_client, email="csrf-missing@example.com")

    response = auth_client.post(_PROTECTED_PATH)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == "csrf_failed"


def test_cookie_authenticated_post_with_matching_csrf_header_succeeds(
    auth_client: TestClient,
) -> None:
    _register(auth_client, email="csrf-ok@example.com")

    response = auth_client.post(_PROTECTED_PATH, headers=_csrf_headers(auth_client))

    assert response.status_code == HTTPStatus.OK


def test_bearer_authenticated_post_does_not_require_csrf(
    auth_app: FastAPI, auth_client: TestClient
) -> None:
    registered = _register(auth_client, email="bearer-csrf@example.com").json()

    with TestClient(auth_app) as bearer_client:
        response = bearer_client.post(
            _PROTECTED_PATH, headers={"Authorization": f"Bearer {registered['access_token']}"}
        )

    assert response.status_code == HTTPStatus.OK


# --- refresh --------------------------------------------------------------------


def test_refresh_rotates_the_session_and_requires_csrf(auth_client: TestClient) -> None:
    registered = _register(auth_client, email="rotate@example.com").json()

    forbidden = auth_client.post(_REFRESH_PATH)
    assert forbidden.status_code == HTTPStatus.FORBIDDEN
    assert forbidden.json()["error"]["code"] == "csrf_failed"

    response = auth_client.post(_REFRESH_PATH, headers=_csrf_headers(auth_client))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["access_token"] != registered["access_token"]
    assert _set_cookie_header(response, REFRESH_COOKIE_NAME)


def test_reusing_a_rotated_refresh_token_after_the_grace_window_is_rejected(
    auth_app: FastAPI, auth_client: TestClient, integration_settings: Settings
) -> None:
    _register(auth_client, email="reuse@example.com")
    original_refresh = auth_client.cookies.get(REFRESH_COOKIE_NAME)
    assert original_refresh is not None

    first = auth_client.post(_REFRESH_PATH, headers=_csrf_headers(auth_client))
    assert first.status_code == HTTPStatus.OK
    current_csrf = auth_client.cookies.get(CSRF_COOKIE_NAME)
    assert current_csrf is not None

    time.sleep(integration_settings.refresh_reuse_grace_seconds + 1)

    response = _replay_refresh(auth_app, refresh_token=original_refresh, csrf_token=current_csrf)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"
    assert "max-age=0" in _set_cookie_header(response, ACCESS_COOKIE_NAME).lower()
    assert "max-age=0" in _set_cookie_header(response, REFRESH_COOKIE_NAME).lower()


# --- logout ---------------------------------------------------------------------


def test_logout_clears_cookies_and_the_refresh_token_stops_working(
    auth_app: FastAPI, auth_client: TestClient
) -> None:
    _register(auth_client, email="logout@example.com")
    refresh_token = auth_client.cookies.get(REFRESH_COOKIE_NAME)
    csrf_token = auth_client.cookies.get(CSRF_COOKIE_NAME)
    assert refresh_token is not None
    assert csrf_token is not None

    response = auth_client.post(_LOGOUT_PATH)

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert "max-age=0" in _set_cookie_header(response, ACCESS_COOKIE_NAME).lower()
    assert "max-age=0" in _set_cookie_header(response, REFRESH_COOKIE_NAME).lower()
    assert "max-age=0" in _set_cookie_header(response, CSRF_COOKIE_NAME).lower()

    # Sign-out is final: even an immediate replay of the pre-logout refresh cookie
    # is rejected, with no reuse-grace window.
    after_logout = _replay_refresh(auth_app, refresh_token=refresh_token, csrf_token=csrf_token)
    assert after_logout.status_code == HTTPStatus.UNAUTHORIZED
    assert "max-age=0" in _set_cookie_header(after_logout, ACCESS_COOKIE_NAME).lower()
    assert "max-age=0" in _set_cookie_header(after_logout, REFRESH_COOKIE_NAME).lower()


# --- token ------------------------------------------------------------------------


def test_token_endpoint_returns_a_usable_bearer_token_and_creates_no_refresh_token_row(
    auth_client: TestClient, db_session: Session
) -> None:
    _register(auth_client, email="token-user@example.com")
    rows_before = db_session.execute(select(func.count()).select_from(RefreshToken)).scalar_one()

    response = auth_client.post(
        _TOKEN_PATH, data={"username": "token-user@example.com", "password": _PASSWORD}
    )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["token_type"] == "bearer"  # noqa: S105 -- a token kind label, not a credential
    assert "set-cookie" not in response.headers
    rows_after = db_session.execute(select(func.count()).select_from(RefreshToken)).scalar_one()
    assert rows_after == rows_before

    me_response = auth_client.get(
        _ME_PATH, headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me_response.status_code == HTTPStatus.OK
    assert me_response.json()["email"] == "token-user@example.com"


# --- OpenAPI ------------------------------------------------------------------------


def test_openapi_documents_the_auth_routes_and_the_oauth2_scheme(
    auth_client: TestClient,
) -> None:
    response = auth_client.get("/openapi.json")

    assert response.status_code == HTTPStatus.OK
    schema = response.json()
    paths = schema["paths"]
    for path in (
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/token",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
    ):
        assert path in paths
    security_schemes = schema["components"]["securitySchemes"]
    assert any(scheme["type"] == "oauth2" for scheme in security_schemes.values())


def test_openapi_documents_a_401_response_for_me(auth_client: TestClient) -> None:
    response = auth_client.get("/openapi.json")

    assert response.status_code == HTTPStatus.OK
    schema = response.json()
    me_responses = schema["paths"]["/api/v1/auth/me"]["get"]["responses"]
    assert me_responses["401"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ErrorResponse"
    )
