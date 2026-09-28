import time
from collections.abc import Iterator

import pytest
from redis import Redis

from app.core.exceptions import RateLimitedError
from app.core.rate_limit import RateLimit, enforce_rate_limit, rate_limit_key
from app.core.redis import get_redis_client

pytestmark = pytest.mark.integration

_RESET_WINDOW_SECONDS = 1


@pytest.fixture
def redis_client(redis_url: str) -> Iterator[Redis]:
    client = get_redis_client(redis_url)
    client.flushdb()
    yield client
    client.flushdb()


def test_limit_calls_pass_then_the_next_call_is_rejected_with_a_positive_retry_after(
    redis_client: Redis,
) -> None:
    rule = RateLimit(scope="test-limit", limit=3, window_seconds=60)
    key = rate_limit_key("user-a")

    for _ in range(rule.limit):
        enforce_rate_limit(redis_client, rule, key)

    with pytest.raises(RateLimitedError) as exc_info:
        enforce_rate_limit(redis_client, rule, key)

    headers = exc_info.value.headers
    assert headers is not None
    assert int(headers["Retry-After"]) > 0


def test_different_keys_are_rate_limited_independently(redis_client: Redis) -> None:
    rule = RateLimit(scope="test-independent", limit=1, window_seconds=60)
    key_a = rate_limit_key("user-a")
    key_b = rate_limit_key("user-b")

    enforce_rate_limit(redis_client, rule, key_a)
    with pytest.raises(RateLimitedError):
        enforce_rate_limit(redis_client, rule, key_a)

    enforce_rate_limit(redis_client, rule, key_b)


def test_the_counter_resets_after_the_window_expires(redis_client: Redis) -> None:
    rule = RateLimit(scope="test-reset", limit=1, window_seconds=_RESET_WINDOW_SECONDS)
    key = rate_limit_key("user-a")

    enforce_rate_limit(redis_client, rule, key)
    with pytest.raises(RateLimitedError):
        enforce_rate_limit(redis_client, rule, key)

    time.sleep(_RESET_WINDOW_SECONDS + 0.1)

    enforce_rate_limit(redis_client, rule, key)
