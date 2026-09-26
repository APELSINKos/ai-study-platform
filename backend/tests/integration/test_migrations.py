from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.db.base import Base

pytestmark = pytest.mark.integration

BACKEND_DIR: Final = Path(__file__).resolve().parents[2]
MIN_PGVECTOR_VERSION: Final = (0, 8)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _vector_version(database_url: str) -> str | None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
    finally:
        engine.dispose()
    return None if version is None else str(version)


def test_migrations_upgrade_downgrade_and_upgrade_again(database_url: str) -> None:
    config = _alembic_config(database_url)

    command.upgrade(config, "head")
    assert _vector_version(database_url) is not None

    command.downgrade(config, "base")
    assert _vector_version(database_url) is None

    command.upgrade(config, "head")
    assert _vector_version(database_url) is not None


def test_pgvector_supports_iterative_index_scans(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")

    version = _vector_version(database_url)

    assert version is not None
    assert tuple(int(part) for part in version.split(".")[:2]) >= MIN_PGVECTOR_VERSION


def test_models_and_migrations_are_in_sync(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()

    assert diff == []
