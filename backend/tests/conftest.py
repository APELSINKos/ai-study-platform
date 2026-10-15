import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import get_engine
from app.main import create_app

FRONTEND_ORIGIN = "http://localhost:3000"
MAINTENANCE_DATABASE = "postgres"
BACKEND_DIR: Final = Path(__file__).resolve().parents[1]


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


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        cors_origins=[FRONTEND_ORIGIN],
        llm_provider="mock",
        embedding_provider="mock",
        storage_dir=tmp_path,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _required_env("TEST_DATABASE_URL")
    _ensure_database_exists(url)
    return url


@pytest.fixture(scope="session")
def redis_url() -> str:
    return _required_env("TEST_REDIS_URL")


@pytest.fixture
def integration_settings(database_url: str, redis_url: str, tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=database_url,
        redis_url=redis_url,
        llm_provider="mock",
        embedding_provider="mock",
        storage_dir=tmp_path,
    )


@pytest.fixture(scope="session")
def _migrated_database(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")


@pytest.fixture
def db_connection(database_url: str, _migrated_database: None) -> Iterator[Connection]:
    """The test's connection, inside a transaction that is rolled back afterwards."""
    connection = get_engine(database_url).connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def db_session(db_connection: Connection) -> Iterator[Session]:
    session = Session(
        bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def session_factory(db_connection: Connection) -> sessionmaker[Session]:
    """Sessions like the worker's, each in a savepoint of the test's connection.

    In the worker every session has a connection of its own, and two open at once could
    wait on each other's locks; here they would share one connection and never wait. So a
    session opened while another one is still open fails the test.
    """
    open_sessions: list[Session] = []

    class OneAtATimeSession(Session):
        def __init__(self, **kwargs: Any) -> None:
            if open_sessions:
                pytest.fail("A session was opened while another one was still open.")
            super().__init__(**kwargs)
            open_sessions.append(self)

        def close(self) -> None:
            if self in open_sessions:
                open_sessions.remove(self)
            super().close()

    factory: sessionmaker[Session] = sessionmaker(
        bind=db_connection,
        class_=OneAtATimeSession,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    return factory
