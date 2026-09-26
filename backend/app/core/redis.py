from functools import lru_cache
from typing import Final

from redis import Redis

REDIS_TIMEOUT_SECONDS: Final = 2.0


@lru_cache
def get_redis_client(redis_url: str) -> Redis:
    return Redis.from_url(
        redis_url,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        decode_responses=True,
    )
