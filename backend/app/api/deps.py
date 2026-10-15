import ipaddress
from collections.abc import Iterator
from typing import Annotated, Final, cast

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.redis import get_redis_client
from app.core.request_auth import authenticate_request, check_csrf
from app.db.session import get_session_factory
from app.documents.storage import FileStorage
from app.models.user import User
from app.services.auth import AuthService
from app.services.workspaces import WorkspaceService

_IPV6_RATE_LIMIT_PREFIX_BITS: Final = 64


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


def get_storage(settings: SettingsDep) -> FileStorage:
    return FileStorage(settings.storage_dir)


StorageDep = Annotated[FileStorage, Depends(get_storage)]


def get_workspace_service(db: DbSession, storage: StorageDep) -> WorkspaceService:
    return WorkspaceService(db, storage)


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]

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
    check_csrf(request.headers, request.cookies)


def get_current_user(
    request: Request,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
    # Never read (authenticate_request parses the header itself); declared so that OpenAPI
    # documents the bearer scheme on every route that needs a signed-in user.
    _bearer_token: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> User:
    user_id = authenticate_request(
        request.method,
        request.headers,
        request.cookies,
        secret=settings.secret_key.get_secret_value(),
    )
    user = auth_service.get_active_user(user_id)
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
