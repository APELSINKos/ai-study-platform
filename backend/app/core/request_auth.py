import secrets
import uuid
from collections.abc import Mapping
from typing import Final

from fastapi.security.utils import get_authorization_scheme_param
from starlette.datastructures import Headers

from app.api.cookies import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token

_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
_BEARER_SCHEME: Final = "bearer"
_CSRF_FAILED_MESSAGE: Final = "The request could not be verified."


def check_csrf(headers: Headers, cookies: Mapping[str, str]) -> None:
    """Double-submit CSRF check: the cookie and header token must match.

    Meaningful only for cookie-authenticated requests: a cross-site page can trigger
    the cookie automatically but cannot read it to reproduce it in the header.
    """
    cookie_token = cookies.get(CSRF_COOKIE_NAME)
    header_token = headers.get(CSRF_HEADER_NAME)
    # Compared as bytes: compare_digest raises TypeError on non-ASCII strings, and any
    # client can send non-ASCII header bytes.
    tokens_match = (
        cookie_token is not None
        and header_token is not None
        and secrets.compare_digest(cookie_token.encode(), header_token.encode())
    )
    if not tokens_match:
        raise PermissionDeniedError(_CSRF_FAILED_MESSAGE, code="csrf_failed")


def _read_bearer_token(headers: Headers) -> str | None:
    """The token of an `Authorization: Bearer` header, read the way OAuth2PasswordBearer does."""
    authorization = headers.get("Authorization")
    scheme, token = get_authorization_scheme_param(authorization)
    if not authorization or scheme.lower() != _BEARER_SCHEME:
        return None
    return token


def authenticate_request(
    method: str, headers: Headers, cookies: Mapping[str, str], *, secret: str
) -> uuid.UUID:
    """The user id in the request's access token: the bearer header first, else the cookie,
    which on an unsafe method also needs the CSRF header.

    Needs no database, so it can run before the request body is read; whether that user
    still exists and is active is for the caller to check.
    """
    token = _read_bearer_token(headers)
    from_cookie = token is None
    if token is None:
        token = cookies.get(ACCESS_COOKIE_NAME)
    if token is None:
        raise AuthenticationError()
    if from_cookie and method not in _SAFE_METHODS:
        check_csrf(headers, cookies)
    return decode_access_token(token, secret=secret)
