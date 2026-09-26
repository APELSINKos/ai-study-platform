import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import Settings

MAINTENANCE_DATABASE = "postgres"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set; integration tests need PostgreSQL and Redis")
    return value


def _ensure_database_exists(database_url: str) -> None:
    target = make_url(database_url)
    engine = create_engine(target.set(database=MAINTENANCE_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
            ).scalar()
            if not exists:
                quoted = engine.dialect.identifier_preparer.quote(str(target.database))
                connection.exec_driver_sql(f"CREATE DATABASE {quoted}")
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _required_env("TEST_DATABASE_URL")
    _ensure_database_exists(url)
    return url


@pytest.fixture(scope="session")
def redis_url() -> str:
    return _required_env("TEST_REDIS_URL")


@pytest.fixture
def integration_settings(database_url: str, redis_url: str) -> Settings:
    return Settings(environment="test", database_url=database_url, redis_url=redis_url)
