import ipaddress
import secrets
from collections.abc import Iterator
from typing import Annotated, Final, cast

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from redis import Redis
from sqlalchemy.orm import Session

from app.api.cookies import ACCESS_COOKIE_NAME, CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.redis import get_redis_client
from app.core.security import decode_access_token
from app.db.session import get_session_factory
from app.models.user import User
from app.services.auth import AuthService

_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
_IPV6_RATE_LIMIT_PREFIX_BITS: Final = 64
_CSRF_FAILED_MESSAGE: Final = "The request could not be verified."


def get_request_settings(request: Request) -> Settings:
    return cast("Settings", request.app.state.settings)


SettingsDep = Annotated[Settings, Depends(get_request_settings)]


def get_db(settings: SettingsDep) -> Iterator[Session]:
    with get_session_factory(settings.database_url)() as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def get_redis(settings: SettingsDep) -> Redis:
    return get_redis_client(settings.redis_url)


RedisClient = Annotated[Redis, Depends(get_redis)]


def get_auth_service(db: DbSession, settings: SettingsDep) -> AuthService:
    return AuthService(db, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

# tokenUrl points Swagger's "Authorize" dialog at /api/v1/auth/token; auto_error is
# disabled because a missing bearer token is not necessarily a failure here, the
# recall_access cookie is an equally valid way to authenticate.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def collapse_ipv6(address: str) -> str:
    """Collapse an IPv6 address to its /64 network (one host can own a whole /64);
    IPv4 addresses and non-IP strings pass through unchanged."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    if not isinstance(parsed, ipaddress.IPv6Address):
        return address
    network = ipaddress.ip_network(f"{address}/{_IPV6_RATE_LIMIT_PREFIX_BITS}", strict=False)
    return str(network.network_address)


def client_ip(request: Request) -> str:
    host = request.client.host if request.client is not None else "unknown"
    return collapse_ipv6(host)


def verify_csrf(request: Request) -> None:
    """Double-submit CSRF check: the cookie and header token must match.

    Meaningful only for cookie-authenticated requests: a cross-site page can trigger
    the cookie automatically but cannot read it to reproduce it in the header.
    """
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    tokens_match = (
        cookie_token is not None
        and header_token is not None
        and secrets.compare_digest(cookie_token, header_token)
    )
    if not tokens_match:
        raise PermissionDeniedError(_CSRF_FAILED_MESSAGE, code="csrf_failed")


def get_current_user(
    request: Request,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
    bearer_token: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> User:
    token = bearer_token
    from_cookie = token is None
    if from_cookie:
        token = request.cookies.get(ACCESS_COOKIE_NAME)
    if token is None:
        raise AuthenticationError()
    if from_cookie and request.method not in _SAFE_METHODS:
        verify_csrf(request)
    user_id = decode_access_token(token, secret=settings.secret_key.get_secret_value())
    user = auth_service.get_active_user(user_id)
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
