from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.redis import get_redis_client
from app.db.session import get_session_factory


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
