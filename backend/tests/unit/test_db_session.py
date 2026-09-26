from typing import Any

import pytest
from sqlalchemy import event

from app.db.session import DATABASE_CONNECT_TIMEOUT_SECONDS, get_engine

DATABASE_URL = "postgresql+psycopg://study:study@db.invalid:5432/study"


class _StopBeforeConnectError(Exception):
    """Raised from the do_connect hook so no real network I/O happens."""


def test_engine_bounds_the_postgres_connect_timeout() -> None:
    get_engine.cache_clear()
    engine = get_engine(DATABASE_URL)
    recorded_cparams: dict[str, Any] = {}

    @event.listens_for(engine, "do_connect")
    def _capture_and_stop(
        dialect: object, conn_rec: object, cargs: list[object], cparams: dict[str, Any]
    ) -> None:
        recorded_cparams.update(cparams)
        raise _StopBeforeConnectError

    try:
        with pytest.raises(_StopBeforeConnectError):
            engine.connect()
    finally:
        get_engine.cache_clear()

    assert recorded_cparams["connect_timeout"] == DATABASE_CONNECT_TIMEOUT_SECONDS
