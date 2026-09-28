import hashlib
from dataclasses import dataclass
from typing import Final, cast

import structlog
from redis import Redis
from redis.exceptions import RedisError

from app.core.exceptions import RateLimitedError

logger = structlog.get_logger(__name__)

_KEY_DIGEST_LENGTH: Final = 32
_MIN_RETRY_AFTER_SECONDS: Final = 1
_KEY_PART_SEPARATOR: Final = "|"


@dataclass(frozen=True)
class RateLimit:
    """A fixed-window rate limiting rule: at most `limit` calls per `window_seconds`."""

    scope: str
    limit: int
    window_seconds: int


def rate_limit_key(*parts: str) -> str:
    """Hash the identifying parts so raw values (e.g. e-mail addresses) never appear in Redis."""
    digest = hashlib.sha256(_KEY_PART_SEPARATOR.join(parts).encode()).hexdigest()
    return digest[:_KEY_DIGEST_LENGTH]


def enforce_rate_limit(redis: Redis, rule: RateLimit, key: str) -> None:
    """Enforce a fixed-window rate limit backed by Redis.

    Fails open: if Redis is unreachable or errors, the call is allowed through
    (with a logged warning) rather than blocked, because authentication must
    keep working even when Redis is down.
    """
    redis_key = f"ratelimit:{rule.scope}:{key}"
    try:
        with redis.pipeline() as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, rule.window_seconds, nx=True)
            count, _ = pipe.execute()
        if count > rule.limit:
            ttl = cast(int, redis.ttl(redis_key))
            retry_after = max(ttl, _MIN_RETRY_AFTER_SECONDS)
            raise RateLimitedError(headers={"Retry-After": str(retry_after)})
    except RedisError:
        logger.warning("rate_limit_unavailable", scope=rule.scope, exc_info=True)
