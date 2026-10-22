"""One user's uploads and retries running at the same time, each on a connection of its own.

The other integration tests share one connection, so their requests can never wait for each
other. Here every request commits for real, and the rows are removed afterwards.
"""

import hashlib
import io
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import pytest
from fastapi import UploadFile
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.session import get_engine
from app.documents.storage import FileStorage
from app.models.document import ACTIVE_DOCUMENT_STATUSES, Document
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.services.documents import DocumentService

pytestmark = pytest.mark.integration

# Bounds every wait, so a request that never gets where the test expects fails the test.
_WAIT_SECONDS: Final = 10.0
_POLL_SECONDS: Final = 0.01
# Whether another connection waits for a lock that the connection with this pid holds.
_BLOCKS_ANOTHER: Final = text(
    "SELECT EXISTS (SELECT FROM pg_stat_activity WHERE :pid = ANY (pg_blocking_pids(pid)))"
)

type _Request = Callable[[DocumentService, User], str]


@dataclass(frozen=True, slots=True)
class _Owner:
    user_id: uuid.UUID
    workspace_id: uuid.UUID


class _Queue:
    def enqueue(self, document_id: uuid.UUID) -> None:
        return None


class _Race:
    """Two requests of one user, the second started once the first has checked the caps.

    The first is then held before its commit until the second has finished or waits for a
    lock that the first holds. Nothing else makes one wait for the other, so without such a
    lock both check the caps against the documents committed before either of them.
    """

    def __init__(self, engine: Engine, settings: Settings, owner: _Owner) -> None:
        self._engine = engine
        self._settings = settings
        self._owner = owner
        self._first_checked = threading.Event()
        self._second_done = threading.Event()
        self._first_thread: threading.Thread | None = None
        self._first_pid: int | None = None

    def hold_the_first(self) -> None:
        if threading.current_thread() is not self._first_thread:
            return
        self._first_checked.set()
        deadline = time.monotonic() + _WAIT_SECONDS
        while not (self._second_done.is_set() or self._first_blocks_another()):
            if time.monotonic() > deadline:
                raise TimeoutError("The second request neither finished nor waited.")
            time.sleep(_POLL_SECONDS)

    def run(self, first: _Request, second: _Request) -> tuple[str, str]:
        results: dict[str, str] = {}
        first_thread = threading.Thread(target=self._record, args=(results, "first", first))
        second_thread = threading.Thread(target=self._record, args=(results, "second", second))
        self._first_thread = first_thread
        first_thread.start()
        self._first_checked.wait(_WAIT_SECONDS)
        second_thread.start()
        for thread in (first_thread, second_thread):
            thread.join(_WAIT_SECONDS * 2)
        return results.get("first", "unfinished"), results.get("second", "unfinished")

    def _record(self, results: dict[str, str], name: str, request: _Request) -> None:
        try:
            results[name] = self._send(request, is_first=name == "first")
        except AppError as error:
            results[name] = error.code
        except Exception as error:
            # Shown in the failed assertion rather than lost in the thread.
            results[name] = repr(error)
        finally:
            if name == "second":
                self._second_done.set()

    def _send(self, request: _Request, *, is_first: bool) -> str:
        # A connection of its own for the whole request, as a request in the API has.
        with self._engine.connect() as connection:
            pid: int = connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            connection.commit()
            if is_first:
                self._first_pid = pid
            with Session(bind=connection, autoflush=False, expire_on_commit=False) as session:
                user = session.get(User, self._owner.user_id)
                assert user is not None
                storage = FileStorage(self._settings.storage_dir)
                service = DocumentService(session, storage, _Queue(), self._settings)
                return request(service, user)

    def _first_blocks_another(self) -> bool:
        with self._engine.connect() as connection:
            blocks: bool = connection.execute(
                _BLOCKS_ANOTHER, {"pid": self._first_pid}
            ).scalar_one()
        return blocks


def _upload_of(owner: _Owner, content: bytes) -> _Request:
    def upload(service: DocumentService, user: User) -> str:
        upload = UploadFile(io.BytesIO(content), filename="notes.txt", size=len(content))
        view = service.upload(user=user, workspace_id=owner.workspace_id, upload=upload)
        return view.document.status

    return upload


def _retry_of(document_id: uuid.UUID) -> _Request:
    def retry(service: DocumentService, user: User) -> str:
        return service.retry(user=user, document_id=document_id).document.status

    return retry


def _failed_document(engine: Engine, owner: _Owner) -> uuid.UUID:
    document_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            Document(
                id=document_id,
                workspace_id=owner.workspace_id,
                original_filename="notes.md",
                content_type="text/markdown",
                size_bytes=1024,
                sha256=hashlib.sha256(document_id.bytes).hexdigest(),
                storage_key=f"{owner.workspace_id}/{document_id}.md",
                status="failed",
                error_code="no_text",
            )
        )
        session.commit()
    return document_id


def _usage(engine: Engine, owner: _Owner) -> tuple[int, int]:
    """The owner's active documents and stored bytes, as committed."""
    statement = select(
        func.count().filter(Document.status.in_(ACTIVE_DOCUMENT_STATUSES)),
        func.coalesce(func.sum(Document.size_bytes), 0),
    ).where(Document.workspace_id == owner.workspace_id)
    with Session(engine) as session:
        active, stored = session.execute(statement).one()
    return active, stored


@pytest.fixture
def engine(database_url: str, _migrated_database: None) -> Engine:
    return get_engine(database_url)


@pytest.fixture
def owner(engine: Engine) -> Iterator[_Owner]:
    """A user with a workspace, committed so that every connection sees them."""
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            User(
                id=user_id,
                email=f"{user_id.hex}@example.com",
                password_hash="hash",
                display_name="Owner",
            )
        )
        session.flush()
        session.add(Workspace(id=workspace_id, owner_id=user_id, name="Algorithms"))
        session.commit()
    try:
        yield _Owner(user_id, workspace_id)
    finally:
        with Session(engine) as session:
            # Its workspace and documents go with it.
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


@pytest.fixture
def held_after_the_upload_check(
    engine: Engine,
    integration_settings: Settings,
    owner: _Owner,
    monkeypatch: pytest.MonkeyPatch,
) -> _Race:
    race = _Race(engine, integration_settings, owner)
    commit_temp = FileStorage.commit_temp

    # Moving the file comes after an upload's last cap check and before its commit.
    def commit_temp_then_hold(storage: FileStorage, temp_path: Path, key: str) -> None:
        commit_temp(storage, temp_path, key)
        race.hold_the_first()

    monkeypatch.setattr(FileStorage, "commit_temp", commit_temp_then_hold)
    return race


@pytest.fixture
def held_after_the_retry_check(
    engine: Engine,
    integration_settings: Settings,
    owner: _Owner,
    monkeypatch: pytest.MonkeyPatch,
) -> _Race:
    race = _Race(engine, integration_settings, owner)
    mark_for_retry = DocumentRepository.mark_for_retry

    # The compare-and-set comes after a retry's cap check and before its commit.
    def mark_for_retry_then_hold(
        repository: DocumentRepository,
        document_id: uuid.UUID,
        workspace_id: uuid.UUID,
        now: datetime,
    ) -> bool:
        marked = mark_for_retry(repository, document_id, workspace_id, now)
        race.hold_the_first()
        return marked

    monkeypatch.setattr(DocumentRepository, "mark_for_retry", mark_for_retry_then_hold)
    return race


def test_of_two_uploads_at_once_only_one_fits_under_the_active_documents_cap(
    engine: Engine,
    integration_settings: Settings,
    owner: _Owner,
    held_after_the_upload_check: _Race,
) -> None:
    integration_settings.max_active_documents_per_user = 1

    results = held_after_the_upload_check.run(
        _upload_of(owner, b"First lecture\n"), _upload_of(owner, b"Second lecture\n")
    )

    assert results == ("uploaded", "too_many_active_documents")
    assert _usage(engine, owner)[0] == 1


def test_of_two_uploads_at_once_only_one_fits_into_the_storage_quota(
    engine: Engine,
    integration_settings: Settings,
    owner: _Owner,
    held_after_the_upload_check: _Race,
) -> None:
    integration_settings.max_storage_bytes_per_user = 10

    results = held_after_the_upload_check.run(
        _upload_of(owner, b"first\n"), _upload_of(owner, b"second")
    )

    assert results == ("uploaded", "storage_quota_exceeded")
    assert _usage(engine, owner)[1] == len(b"first\n")


def test_of_two_retries_at_once_only_one_fits_under_the_active_documents_cap(
    engine: Engine,
    integration_settings: Settings,
    owner: _Owner,
    held_after_the_retry_check: _Race,
) -> None:
    integration_settings.max_active_documents_per_user = 1
    first = _failed_document(engine, owner)
    second = _failed_document(engine, owner)

    results = held_after_the_retry_check.run(_retry_of(first), _retry_of(second))

    assert results == ("uploaded", "too_many_active_documents")
    assert _usage(engine, owner)[0] == 1


def test_the_lock_on_a_user_holds_up_only_another_such_lock(engine: Engine, owner: _Owner) -> None:
    with Session(engine) as holder, Session(engine) as other:
        UserRepository(holder).lock(owner.user_id)
        # Fails soon rather than hangs the test when the statement waits for the lock.
        other.execute(text("SET LOCAL lock_timeout = '1s'"))

        # A new workspace only needs the user's key, so the lock does not hold it up.
        other.add(Workspace(owner_id=owner.user_id, name="Statistics"))
        other.flush()
        with pytest.raises(OperationalError, match="lock timeout"):
            UserRepository(other).lock(owner.user_id)
