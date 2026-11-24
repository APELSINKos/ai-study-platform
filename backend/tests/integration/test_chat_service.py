"""ChatService transaction ordering, rollback semantics, FK races and two-connection concurrency."""

import hashlib
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Connection, Engine, delete, event, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.db.session import get_engine
from app.llm.base import AnalysisRequest, AnalysisResult, ChatRequest, ChatResult
from app.llm.mock_provider import (
    MOCK_ANALYSIS_MODEL,
    MOCK_EMBEDDING_MODEL,
    HashingEmbeddingProvider,
    MockLLMProvider,
)
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chat import ChatRepository
from app.repositories.document_chunks import ChunkRow, DocumentChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.chat import MAX_MESSAGES_PER_SESSION, ChatSessionCreateRequest
from app.services.chat import ChatService

pytestmark = pytest.mark.integration

_START: Final = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
_WAIT_SECONDS: Final = 10.0
_POLL_SECONDS: Final = 0.01
_BLOCKS_ANOTHER: Final = text(
    "SELECT EXISTS (SELECT FROM pg_stat_activity WHERE :pid = ANY (pg_blocking_pids(pid)))"
)
_LOCK_STATEMENT_RE: Final = re.compile(
    r"UPDATE workspaces\b|FOR UPDATE OF chat_sessions\b", re.IGNORECASE
)
_CHUNK_TEXT: Final = "Each review makes the next loss slower than the one before."
_QUESTION: Final = "How does review affect forgetting?"


class _FakeClock:
    def __init__(self, start: datetime = _START) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class _HookedLLM:
    def __init__(self, on_call: Callable[[ChatRequest], None] | None = None) -> None:
        self._builtin = MockLLMProvider()
        self.on_call = on_call

    @property
    def model_name(self) -> str:
        return MOCK_ANALYSIS_MODEL

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult:
        return self._builtin.analyze_document(request)

    def answer_question(
        self, request: ChatRequest, *, timeout_budget_seconds: float | None = None
    ) -> ChatResult:
        if self.on_call is not None:
            self.on_call(request)
        return self._builtin.answer_question(request, timeout_budget_seconds=timeout_budget_seconds)


def _seed_single_connection_chat(
    session: Session,
    clock: _FakeClock,
) -> tuple[User, Workspace, ChatSession]:
    owner = UserRepository(session).add(
        User(email="chat-service@example.com", password_hash="hash", display_name="Owner")
    )
    workspace = WorkspaceRepository(session).add(
        Workspace(owner_id=owner.id, name="Memory", updated_at=_START - timedelta(days=1))
    )
    doc_id = uuid.uuid4()
    document = DocumentRepository(session).add(
        Document(
            id=doc_id,
            workspace_id=workspace.id,
            original_filename="forgetting.md",
            content_type="text/markdown",
            size_bytes=512,
            sha256=hashlib.sha256(doc_id.bytes).hexdigest(),
            storage_key=f"{workspace.id}/{doc_id}.md",
            status="ready",
            chunk_count=1,
            embedding_model=MOCK_EMBEDDING_MODEL,
            processed_at=_START,
        )
    )
    [vector] = HashingEmbeddingProvider().embed([_CHUNK_TEXT])
    DocumentChunkRepository(session).replace_for_document(
        document.id,
        workspace.id,
        [
            ChunkRow(
                chunk_index=0,
                content=_CHUNK_TEXT,
                heading="Spaced repetition",
                page_start=None,
                page_end=None,
                char_count=len(_CHUNK_TEXT),
                embedding=vector,
            )
        ],
    )
    now = clock()
    chat_session = ChatRepository(session).add_session(
        ChatSession(
            workspace_id=workspace.id,
            user_id=owner.id,
            title="Study session",
            document_ids=None,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    return owner, workspace, chat_session


def _seed_messages(session: Session, session_id: uuid.UUID, count: int) -> None:
    rows = [
        ChatMessage(
            session_id=session_id,
            sequence=index,
            role="user" if index % 2 == 1 else "assistant",
            content=f"Turn {index}",
            citations=[],
            insufficient_context=False,
            created_at=_START,
        )
        for index in range(1, count + 1)
    ]
    session.add_all(rows)
    session.commit()


def test_tx3_locks_workspace_before_chat_session_and_advances_workspace_updated_at(
    db_session: Session, integration_settings: Settings
) -> None:
    clock = _FakeClock()
    owner, workspace, chat_session = _seed_single_connection_chat(db_session, clock)
    service = ChatService(
        db_session,
        integration_settings,
        HashingEmbeddingProvider(),
        MockLLMProvider(),
        clock=clock,
    )
    clock.advance(timedelta(minutes=15))
    recorded: list[str] = []

    def record_sql(**event_args: Any) -> None:
        for match in _LOCK_STATEMENT_RE.finditer(event_args["statement"]):
            recorded.append(match.group())

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", record_sql, named=True)
    try:
        service.send_message(user=owner, session_id=chat_session.id, content=_QUESTION)
    finally:
        event.remove(connection, "before_cursor_execute", record_sql)

    assert recorded == ["UPDATE workspaces", "FOR UPDATE OF chat_sessions"]
    db_session.expire_all()
    assert workspace.updated_at == _START + timedelta(minutes=15)


def test_tx3_rollback_on_concurrent_session_delete_leaves_workspace_updated_at_untouched(
    db_session: Session, db_connection: Connection, integration_settings: Settings
) -> None:
    clock = _FakeClock()
    owner, workspace, chat_session = _seed_single_connection_chat(db_session, clock)
    touched_before = workspace.updated_at

    def delete_during_llm(_request: ChatRequest) -> None:
        db_connection.execute(
            text("DELETE FROM chat_sessions WHERE id = :id"), {"id": chat_session.id}
        )

    service = ChatService(
        db_session,
        integration_settings,
        HashingEmbeddingProvider(),
        _HookedLLM(on_call=delete_during_llm),
        clock=clock,
    )
    clock.advance(timedelta(minutes=20))

    with pytest.raises(NotFoundError) as exc_info:
        service.send_message(user=owner, session_id=chat_session.id, content=_QUESTION)

    assert exc_info.value.code == "chat_session_not_found"
    db_session.expire_all()
    assert workspace.updated_at == touched_before


def test_tx3_rollback_on_concurrent_session_limit_leaves_workspace_updated_at_untouched(
    db_session: Session, db_connection: Connection, integration_settings: Settings
) -> None:
    clock = _FakeClock()
    owner, workspace, chat_session = _seed_single_connection_chat(db_session, clock)
    _seed_messages(db_session, chat_session.id, MAX_MESSAGES_PER_SESSION - 2)
    touched_before = workspace.updated_at

    def fill_during_llm(_request: ChatRequest) -> None:
        for seq in (MAX_MESSAGES_PER_SESSION - 1, MAX_MESSAGES_PER_SESSION):
            db_connection.execute(
                text(
                    "INSERT INTO chat_messages "
                    "(id, session_id, sequence, role, content, citations, "
                    "insufficient_context, created_at) "
                    "VALUES (:id, :sid, :seq, :role, :content, '[]'::jsonb, false, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "sid": chat_session.id,
                    "seq": seq,
                    "role": "user" if seq % 2 == 1 else "assistant",
                    "content": f"Concurrent {seq}",
                    "now": _START,
                },
            )

    service = ChatService(
        db_session,
        integration_settings,
        HashingEmbeddingProvider(),
        _HookedLLM(on_call=fill_during_llm),
        clock=clock,
    )
    clock.advance(timedelta(minutes=20))

    with pytest.raises(ConflictError) as exc_info:
        service.send_message(user=owner, session_id=chat_session.id, content=_QUESTION)

    assert exc_info.value.code == "chat_session_limit_reached"
    db_session.expire_all()
    assert workspace.updated_at == touched_before


def test_create_session_maps_concurrent_workspace_delete_fk_error_to_404(
    db_session: Session, integration_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _FakeClock()
    owner, _, _ = _seed_single_connection_chat(db_session, clock)
    vanished = Workspace(id=uuid.uuid4(), owner_id=owner.id, name="Deleted")
    monkeypatch.setattr(WorkspaceRepository, "get_for_owner", lambda *_: vanished)
    service = ChatService(
        db_session,
        integration_settings,
        HashingEmbeddingProvider(),
        MockLLMProvider(),
        clock=clock,
    )

    with pytest.raises(NotFoundError) as exc_info:
        service.create_session(
            user=owner, request=ChatSessionCreateRequest(workspace_id=vanished.id)
        )

    assert exc_info.value.code == "workspace_not_found"


# --- true two-connection concurrency --------------------------------------------


@dataclass(frozen=True, slots=True)
class _CommittedChat:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    session_id: uuid.UUID


class _ChatRace:
    """Two simultaneous chat turns on independent PostgreSQL connections.

    The first turn is held inside Tx 3 after locking the workspace/session and inserting its
    messages, until the second turn either finishes or blocks on the first turn's row lock.
    """

    def __init__(self, engine: Engine, settings: Settings, target: _CommittedChat) -> None:
        self._engine = engine
        self._settings = settings
        self._target = target
        self._first_in_tx3 = threading.Event()
        self._second_done = threading.Event()
        self._first_thread: threading.Thread | None = None
        self._first_pid: int | None = None

    def hold_the_first(self) -> None:
        if threading.current_thread() is not self._first_thread:
            return
        self._first_in_tx3.set()
        deadline = time.monotonic() + _WAIT_SECONDS
        while not (self._second_done.is_set() or self._first_blocks_another()):
            if time.monotonic() > deadline:
                raise TimeoutError("The second chat turn neither finished nor waited on a lock.")
            time.sleep(_POLL_SECONDS)

    def run(self, first_question: str, second_question: str) -> tuple[str, str]:
        results: dict[str, str] = {}
        first_thread = threading.Thread(
            target=self._record, args=(results, "first", first_question)
        )
        second_thread = threading.Thread(
            target=self._record, args=(results, "second", second_question)
        )
        self._first_thread = first_thread
        first_thread.start()
        self._first_in_tx3.wait(_WAIT_SECONDS)
        second_thread.start()
        for thread in (first_thread, second_thread):
            thread.join(_WAIT_SECONDS * 2)
        return results.get("first", "unfinished"), results.get("second", "unfinished")

    def _record(self, results: dict[str, str], name: str, question: str) -> None:
        try:
            results[name] = self._send(question, is_first=name == "first")
        except AppError as error:
            results[name] = error.code
        except Exception as error:
            results[name] = repr(error)
        finally:
            if name == "second":
                self._second_done.set()

    def _send(self, question: str, *, is_first: bool) -> str:
        with self._engine.connect() as connection:
            pid: int = connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            connection.commit()
            if is_first:
                self._first_pid = pid
            with Session(bind=connection, autoflush=False, expire_on_commit=False) as session:
                user = session.get(User, self._target.user_id)
                assert user is not None
                service = ChatService(
                    session,
                    self._settings,
                    HashingEmbeddingProvider(),
                    MockLLMProvider(),
                )
                service.send_message(
                    user=user, session_id=self._target.session_id, content=question
                )
                return "created"

    def _first_blocks_another(self) -> bool:
        with self._engine.connect() as connection:
            blocks: bool = connection.execute(
                _BLOCKS_ANOTHER, {"pid": self._first_pid}
            ).scalar_one()
        return blocks


@pytest.fixture
def engine(database_url: str, _migrated_database: None) -> Engine:
    return get_engine(database_url)


@pytest.fixture
def committed_chat(engine: Engine) -> Iterator[_CommittedChat]:
    """A committed user, workspace, ready chunk and session visible across connections."""
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    session_id = uuid.uuid4()
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
        session.add(Workspace(id=workspace_id, owner_id=user_id, name="Concurrency"))
        session.flush()
        session.add(
            Document(
                id=doc_id,
                workspace_id=workspace_id,
                original_filename="forgetting.md",
                content_type="text/markdown",
                size_bytes=512,
                sha256=hashlib.sha256(doc_id.bytes).hexdigest(),
                storage_key=f"{workspace_id}/{doc_id}.md",
                status="ready",
                chunk_count=1,
                embedding_model=MOCK_EMBEDDING_MODEL,
                processed_at=_START,
            )
        )
        session.flush()
        [vector] = HashingEmbeddingProvider().embed([_CHUNK_TEXT])
        DocumentChunkRepository(session).replace_for_document(
            doc_id,
            workspace_id,
            [
                ChunkRow(
                    chunk_index=0,
                    content=_CHUNK_TEXT,
                    heading="Spaced repetition",
                    page_start=None,
                    page_end=None,
                    char_count=len(_CHUNK_TEXT),
                    embedding=vector,
                )
            ],
        )
        session.add(
            ChatSession(
                id=session_id,
                workspace_id=workspace_id,
                user_id=user_id,
                title="Concurrent session",
                document_ids=None,
                created_at=_START,
                updated_at=_START,
            )
        )
        session.commit()
    try:
        yield _CommittedChat(user_id=user_id, workspace_id=workspace_id, session_id=session_id)
    finally:
        with Session(engine) as session:
            session.execute(delete(User).where(User.id == user_id))
            session.commit()


@pytest.fixture
def held_in_tx3(
    engine: Engine,
    integration_settings: Settings,
    committed_chat: _CommittedChat,
    monkeypatch: pytest.MonkeyPatch,
) -> _ChatRace:
    race = _ChatRace(engine, integration_settings, committed_chat)
    original_add_messages = ChatRepository.add_messages

    def add_messages_then_hold(repository: ChatRepository, messages: Sequence[ChatMessage]) -> None:
        original_add_messages(repository, messages)
        race.hold_the_first()

    monkeypatch.setattr(ChatRepository, "add_messages", add_messages_then_hold)
    return race


def _sequences(engine: Engine, session_id: uuid.UUID) -> list[int]:
    with Session(engine) as session:
        statement = (
            select(ChatMessage.sequence)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.asc())
        )
        return list(session.execute(statement).scalars())


def test_two_simultaneous_turns_at_session_limit_allow_one_and_reject_other_without_collisions(
    engine: Engine, committed_chat: _CommittedChat, held_in_tx3: _ChatRace
) -> None:
    with Session(engine) as session:
        _seed_messages(session, committed_chat.session_id, MAX_MESSAGES_PER_SESSION - 2)

    results = held_in_tx3.run(_QUESTION, _QUESTION)

    assert results == ("created", "chat_session_limit_reached")
    assert _sequences(engine, committed_chat.session_id) == list(
        range(1, MAX_MESSAGES_PER_SESSION + 1)
    )


def test_two_simultaneous_turns_below_limit_serialize_with_contiguous_sequences(
    engine: Engine, committed_chat: _CommittedChat, held_in_tx3: _ChatRace
) -> None:
    results = held_in_tx3.run(_QUESTION, _QUESTION)

    assert results == ("created", "created")
    assert _sequences(engine, committed_chat.session_id) == [1, 2, 3, 4]
