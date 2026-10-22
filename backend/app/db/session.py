from functools import lru_cache
from typing import Final

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_CONNECT_TIMEOUT_SECONDS: Final = 3


@lru_cache
def get_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": DATABASE_CONNECT_TIMEOUT_SECONDS},
        # Leaves the statement's values, such as document text, names and file names, out of
        # the text SQLAlchemy gives a database error. PostgreSQL's own part of that text can
        # still quote a row it refuses, which is why log_unexpected_error never logs it.
        hide_parameters=True,
    )


@lru_cache
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, expire_on_commit=False)
