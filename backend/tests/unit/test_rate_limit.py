import json
from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.logging import configure_logging
from app.core.rate_limit import RateLimit, enforce_rate_limit, rate_limit_key


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


class _BrokenPipeline:
    """Mimics a redis-py pipeline whose execute() fails, e.g. because Redis is down."""

    def __enter__(self) -> "_BrokenPipeline":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def incr(self, name: str) -> "_BrokenPipeline":
        return self

    def expire(self, name: str, time: int, nx: bool = False) -> "_BrokenPipeline":
        return self

    def execute(self) -> list[int]:
        raise RedisConnectionError("could not connect to Redis")


class _BrokenRedis:
    def pipeline(self) -> _BrokenPipeline:
        return _BrokenPipeline()


def test_rate_limit_key_does_not_contain_the_raw_identifying_parts() -> None:
    key = rate_limit_key("login", "person@example.com")

    assert "person@example.com" not in key
    assert len(key) == 32


def test_rate_limit_key_is_deterministic_and_distinguishes_parts() -> None:
    assert rate_limit_key("login", "person@example.com") == rate_limit_key(
        "login", "person@example.com"
    )
    assert rate_limit_key("login", "a") != rate_limit_key("login", "b")


def test_a_broken_redis_lets_the_call_through_and_logs_a_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    rule = RateLimit(scope="login", limit=5, window_seconds=60)

    enforce_rate_limit(_BrokenRedis(), rule, "some-key")  # type: ignore[arg-type]

    [line] = _json_lines(capsys.readouterr().out)
    assert line["event"] == "rate_limit_unavailable"
    assert line["level"] == "warning"
    assert line["scope"] == "login"
    assert "exception" in line
