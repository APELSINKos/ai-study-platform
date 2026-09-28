import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_engine

MAINTENANCE_DATABASE = "postgres"
BACKEND_DIR: Final = Path(__file__).resolve().parents[2]


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


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def _migrated_database(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")


@pytest.fixture
def db_session(database_url: str, _migrated_database: None) -> Iterator[Session]:
    engine = get_engine(database_url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
