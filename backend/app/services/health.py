import time

import structlog
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.timing import to_ms
from app.schemas.health import ComponentHealth, ReadinessResponse

logger = structlog.get_logger(__name__)


def check_database(session: Session) -> ComponentHealth:
    started = time.perf_counter()
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.warning("readiness_check_failed", component="database", exc_info=True)
        return ComponentHealth(status="error")
    return ComponentHealth(status="ok", latency_ms=to_ms(time.perf_counter() - started))


def check_redis(client: Redis) -> ComponentHealth:
    started = time.perf_counter()
    try:
        client.ping()
    except RedisError:
        logger.warning("readiness_check_failed", component="redis", exc_info=True)
        return ComponentHealth(status="error")
    return ComponentHealth(status="ok", latency_ms=to_ms(time.perf_counter() - started))


def readiness_report(session: Session, redis_client: Redis) -> ReadinessResponse:
    checks = {"database": check_database(session), "redis": check_redis(redis_client)}
    healthy = all(check.status == "ok" for check in checks.values())
    return ReadinessResponse(status="ok" if healthy else "unavailable", checks=checks)
