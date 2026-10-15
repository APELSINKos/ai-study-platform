import uuid
from datetime import timedelta
from typing import Final

import pytest
from starlette.datastructures import Headers

from app.api.cookies import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.core.clock import utcnow
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.request_auth import authenticate_request
from app.core.security import create_access_token

# 32 bytes or more: pyjwt warns (and filterwarnings turns it into an error) about shorter
# HMAC keys.
SECRET: Final = "request-auth-unit-test-signing-key"
CSRF_TOKEN: Final = "csrf-token-of-the-signed-in-session"


def _token(user_id: uuid.UUID, *, ttl: timedelta = timedelta(minutes=15)) -> str:
    return create_access_token(user_id, secret=SECRET, ttl=ttl, now=utcnow()).value


def _authenticate(method: str, headers: dict[str, str], cookies: dict[str, str]) -> uuid.UUID:
    return authenticate_request(method, Headers(headers), cookies, secret=SECRET)


@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
def test_a_bearer_token_authenticates_an_unsafe_request_without_csrf(scheme: str) -> None:
    user_id = uuid.uuid4()

    assert _authenticate("POST", {"Authorization": f"{scheme} {_token(user_id)}"}, {}) == user_id


def test_the_access_cookie_authenticates_a_safe_request_without_csrf() -> None:
    user_id = uuid.uuid4()

    assert _authenticate("GET", {}, {ACCESS_COOKIE_NAME: _token(user_id)}) == user_id


def test_the_access_cookie_authenticates_an_unsafe_request_with_a_matching_csrf_header() -> None:
    user_id = uuid.uuid4()
    cookies = {ACCESS_COOKIE_NAME: _token(user_id), CSRF_COOKIE_NAME: CSRF_TOKEN}

    assert _authenticate("POST", {CSRF_HEADER_NAME: CSRF_TOKEN}, cookies) == user_id


@pytest.mark.parametrize("csrf_header", [None, "a-token-of-another-session", f"{CSRF_TOKEN}é"])
def test_a_cookie_authenticated_unsafe_request_needs_the_matching_csrf_header(
    csrf_header: str | None,
) -> None:
    cookies = {ACCESS_COOKIE_NAME: _token(uuid.uuid4()), CSRF_COOKIE_NAME: CSRF_TOKEN}
    headers = {} if csrf_header is None else {CSRF_HEADER_NAME: csrf_header}

    with pytest.raises(PermissionDeniedError) as exc_info:
        _authenticate("POST", headers, cookies)

    assert exc_info.value.code == "csrf_failed"


def test_the_csrf_check_comes_before_the_token_is_decoded() -> None:
    with pytest.raises(PermissionDeniedError) as exc_info:
        _authenticate("POST", {}, {ACCESS_COOKIE_NAME: "not-a-token"})

    assert exc_info.value.code == "csrf_failed"


def test_the_bearer_token_takes_precedence_over_the_cookie() -> None:
    bearer_user, cookie_user = uuid.uuid4(), uuid.uuid4()
    headers = {"Authorization": f"Bearer {_token(bearer_user)}"}

    assert _authenticate("POST", headers, {ACCESS_COOKIE_NAME: _token(cookie_user)}) == bearer_user


def test_an_invalid_bearer_token_does_not_fall_back_to_the_cookie() -> None:
    cookies = {ACCESS_COOKIE_NAME: _token(uuid.uuid4())}

    with pytest.raises(AuthenticationError) as exc_info:
        _authenticate("GET", {"Authorization": "Bearer not-a-token"}, cookies)

    assert exc_info.value.code == "invalid_token"


def test_another_authorization_scheme_falls_back_to_the_cookie() -> None:
    user_id = uuid.uuid4()
    headers = {"Authorization": "Basic dXNlcjpwYXNzd29yZA=="}

    assert _authenticate("GET", headers, {ACCESS_COOKIE_NAME: _token(user_id)}) == user_id


def test_a_request_without_credentials_gets_the_bearer_challenge() -> None:
    with pytest.raises(AuthenticationError) as exc_info:
        _authenticate("POST", {}, {})

    assert exc_info.value.code == "not_authenticated"
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


def test_an_expired_token_is_reported_as_expired() -> None:
    expired = _token(uuid.uuid4(), ttl=timedelta(seconds=-1))

    with pytest.raises(AuthenticationError) as exc_info:
        _authenticate("GET", {"Authorization": f"Bearer {expired}"}, {})

    assert exc_info.value.code == "token_expired"
