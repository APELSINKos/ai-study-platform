import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import psycopg
import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.models.chat_message import ChatMessage
from app.models.chat_session import MAX_SCOPE_DOCUMENTS, ChatSession
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.chat import ChatRepository, ChatSessionSummary, SessionTurnStats
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository

pytestmark = pytest.mark.integration

_NOW: Final = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _user(session: Session, email: str = "owner@example.com") -> User:
    return UserRepository(session).add(
        User(email=email, password_hash="hash", display_name="Owner")
    )


def _workspace(session: Session, owner: User, name: str = "Algorithms") -> Workspace:
    return WorkspaceRepository(session).add(Workspace(owner_id=owner.id, name=name))


def _document(session: Session, workspace: Workspace) -> Document:
    document_id = uuid.uuid4()
    return DocumentRepository(session).add(
        Document(
            id=document_id,
            workspace_id=workspace.id,
            original_filename="notes.md",
            content_type="text/markdown",
            size_bytes=512,
            sha256=hashlib.sha256(document_id.bytes).hexdigest(),
            storage_key=f"{workspace.id}/{document_id}.md",
        )
    )


def _chat_session(
    repository: ChatRepository,
    workspace: Workspace,
    *,
    title: str | None = None,
    document_ids: list[uuid.UUID] | None = None,
    updated_at: datetime = _NOW,
) -> ChatSession:
    return repository.add_session(
        ChatSession(
            workspace_id=workspace.id,
            user_id=workspace.owner_id,
            title=title,
            document_ids=document_ids,
            updated_at=updated_at,
        )
    )


def _message(chat_session: ChatSession, **overrides: object) -> ChatMessage:
    sequence = overrides.get("sequence", 1)
    default_role = "user" if isinstance(sequence, int) and sequence % 2 == 1 else "assistant"
    fields: dict[str, object] = {
        "session_id": chat_session.id,
        "sequence": 1,
        "role": default_role,
        "content": f"Message {sequence}",
        "created_at": _NOW,
    }
    fields.update(overrides)
    return ChatMessage(**fields)


def _violated_constraint(error: IntegrityError) -> str | None:
    assert isinstance(error.orig, psycopg.Error)
    return error.orig.diag.constraint_name


def test_add_session_and_get_for_owner_return_session_and_workspace_name(
    db_session: Session,
) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner, "Linear Algebra")
    doc = _document(db_session, workspace)

    created = _chat_session(
        repository,
        workspace,
        title="Eigenvalues",
        document_ids=[doc.id],
    )

    assert isinstance(created.id, uuid.UUID)
    found = repository.get_for_owner(created.id, owner.id)
    assert found == (created, "Linear Algebra")
    assert created.document_ids == [doc.id]
    assert repository.get_for_owner(uuid.uuid4(), owner.id) is None


def test_list_for_owner_returns_workspace_name_message_count_and_deterministic_order(
    db_session: Session,
) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    first_ws = _workspace(db_session, owner, "Algorithms")
    second_ws = _workspace(db_session, owner, "Databases")

    older = _chat_session(repository, first_ws, title="Older", updated_at=_NOW - timedelta(days=2))
    tied = [
        _chat_session(repository, second_ws, title=f"Tied {i}", updated_at=_NOW) for i in range(3)
    ]
    repository.add_messages(
        [_message(older, sequence=1), _message(older, sequence=2), _message(older, sequence=3)]
    )
    repository.add_messages([_message(tied[0], sequence=1)])

    items, total = repository.list_for_owner(owner.id, offset=0, limit=10)

    expected_tied = sorted(tied, key=lambda item: item.id, reverse=True)
    assert [item.session for item in items] == [*expected_tied, older]
    assert total == 4

    by_id = {item.session.id: item for item in items}
    assert by_id[older.id] == ChatSessionSummary(
        session=older, workspace_name="Algorithms", message_count=3
    )
    assert by_id[tied[0].id] == ChatSessionSummary(
        session=tied[0], workspace_name="Databases", message_count=1
    )
    assert by_id[tied[1].id] == ChatSessionSummary(
        session=tied[1], workspace_name="Databases", message_count=0
    )


def test_list_for_owner_supports_pagination_and_workspace_filter(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    target = _workspace(db_session, owner, "Target")
    other = _workspace(db_session, owner, "Other")

    for day in range(5):
        _chat_session(
            repository, target, title=f"Target {day}", updated_at=_NOW - timedelta(days=day)
        )
    _chat_session(repository, other, title="Other 0", updated_at=_NOW)

    page, total = repository.list_for_owner(owner.id, offset=2, limit=2, workspace_id=target.id)
    beyond, beyond_total = repository.list_for_owner(
        owner.id, offset=10, limit=2, workspace_id=target.id
    )
    all_items, all_total = repository.list_for_owner(owner.id, offset=0, limit=10)

    assert [item.session.title for item in page] == ["Target 2", "Target 3"]
    assert total == 5
    assert beyond == []
    assert beyond_total == 5
    assert len(all_items) == 6
    assert all_total == 6


def test_owner_isolation_hides_another_users_sessions(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session, "owner@example.com")
    stranger = _user(db_session, "stranger@example.com")
    workspace = _workspace(db_session, owner, "Private Notes")
    chat_session = _chat_session(repository, workspace, title="Secret")

    assert repository.get_for_owner(chat_session.id, stranger.id) is None
    assert repository.get_for_owner(chat_session.id, stranger.id, for_update=True) is None
    assert repository.list_for_owner(stranger.id, offset=0, limit=10) == ([], 0)
    assert repository.list_for_owner(
        stranger.id, offset=0, limit=10, workspace_id=workspace.id
    ) == ([], 0)
    assert repository.delete_for_owner(chat_session.id, stranger.id) is False
    assert repository.get_for_owner(chat_session.id, owner.id) == (chat_session, "Private Notes")


def test_cross_tenant_session_insert_is_rejected_by_composite_foreign_key(
    db_session: Session,
) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session, "owner@example.com")
    stranger = _user(db_session, "stranger@example.com")
    workspace = _workspace(db_session, owner)

    with pytest.raises(IntegrityError) as caught:
        repository.add_session(ChatSession(workspace_id=workspace.id, user_id=stranger.id))

    assert _violated_constraint(caught.value) == "fk_chat_sessions_workspace_id_workspaces"


def test_session_document_ids_accepts_bounds_and_null(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)

    unscoped = _chat_session(repository, workspace, document_ids=None)
    single = _chat_session(repository, workspace, document_ids=[uuid.uuid4()])
    maximum = _chat_session(
        repository,
        workspace,
        document_ids=[uuid.uuid4() for _ in range(MAX_SCOPE_DOCUMENTS)],
    )

    assert unscoped.document_ids is None
    assert single.document_ids is not None
    assert len(single.document_ids) == 1
    assert maximum.document_ids is not None
    assert len(maximum.document_ids) == MAX_SCOPE_DOCUMENTS


@pytest.mark.parametrize(
    "document_ids",
    [
        pytest.param([], id="empty-array"),
        pytest.param([uuid.uuid4(), None], id="null-element"),
        pytest.param([uuid.uuid4() for _ in range(MAX_SCOPE_DOCUMENTS + 1)], id="too-many"),
    ],
)
def test_session_document_ids_check_rejects_invalid_arrays(
    db_session: Session, document_ids: list[uuid.UUID | None]
) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    invalid_session = ChatSession(
        workspace_id=workspace.id, user_id=owner.id, document_ids=document_ids
    )

    with pytest.raises(IntegrityError) as caught:
        repository.add_session(invalid_session)

    assert _violated_constraint(caught.value) == "ck_chat_sessions_document_ids_valid"


def test_session_document_ids_check_rejects_multidimensional_array(db_session: Session) -> None:
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO chat_sessions (id, workspace_id, user_id, document_ids)"
                " VALUES (:id, :workspace_id, :user_id, ARRAY[[gen_random_uuid()]]::uuid[])"
            ),
            {"id": uuid.uuid4(), "workspace_id": workspace.id, "user_id": owner.id},
        )

    assert _violated_constraint(caught.value) == "ck_chat_sessions_document_ids_valid"


def test_message_defaults_and_valid_boundaries_are_accepted(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    chat_session = _chat_session(repository, workspace)

    repository.add_messages([])
    grounded = _message(
        chat_session,
        sequence=1,
        role="assistant",
        content="Grounded answer [1].",
        citations=[{"index": 1, "chunk_id": str(uuid.uuid4()), "quote": "Evidence."}],
        insufficient_context=False,
        model="mock-chat-v1",
        retrieval_ms=0,
        generation_ms=0,
        prompt_tokens=0,
        completion_tokens=0,
    )
    unanswered = _message(
        chat_session,
        sequence=2,
        role="assistant",
        content="Not enough context.",
        insufficient_context=True,
    )
    repository.add_messages([grounded, unanswered])
    db_session.expire_all()

    stored = repository.list_messages(chat_session.id)
    assert len(stored) == 2
    assert stored[0].citations == grounded.citations
    assert stored[1].citations == []
    assert stored[1].insufficient_context is True


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"sequence": 0}, "ck_chat_messages_sequence_positive", id="sequence-zero"),
        pytest.param(
            {"sequence": -1}, "ck_chat_messages_sequence_positive", id="sequence-negative"
        ),
        pytest.param({"role": "system"}, "ck_chat_messages_role_valid", id="bad-role"),
        pytest.param({"content": ""}, "ck_chat_messages_content_non_empty", id="empty-content"),
        pytest.param(
            {"citations": {"index": 1}},
            "ck_chat_messages_citations_is_array",
            id="citations-object",
        ),
        pytest.param(
            {"insufficient_context": True, "citations": [{"index": 1}]},
            "ck_chat_messages_insufficient_context_no_citations",
            id="insufficient-with-citations",
        ),
        pytest.param(
            {"retrieval_ms": -1}, "ck_chat_messages_retrieval_ms_non_negative", id="retrieval-ms"
        ),
        pytest.param(
            {"generation_ms": -1},
            "ck_chat_messages_generation_ms_non_negative",
            id="generation-ms",
        ),
        pytest.param(
            {"prompt_tokens": -1},
            "ck_chat_messages_prompt_tokens_non_negative",
            id="prompt-tokens",
        ),
        pytest.param(
            {"completion_tokens": -1},
            "ck_chat_messages_completion_tokens_non_negative",
            id="completion-tokens",
        ),
    ],
)
def test_message_checks_reject_invalid_rows(
    db_session: Session, overrides: dict[str, object], constraint: str
) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    chat_session = _chat_session(repository, workspace)

    with pytest.raises(IntegrityError) as caught:
        repository.add_messages([_message(chat_session, **overrides)])

    assert _violated_constraint(caught.value) == constraint


def test_duplicate_sequence_in_same_session_is_rejected(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    chat_session = _chat_session(repository, workspace)
    repository.add_messages([_message(chat_session, sequence=1)])

    with pytest.raises(IntegrityError) as caught:
        repository.add_messages([_message(chat_session, sequence=1, role="assistant")])

    assert _violated_constraint(caught.value) == "uq_chat_messages_session_id_sequence"


def test_list_messages_and_list_recent_messages_order_by_sequence(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    chat_session = _chat_session(repository, workspace)
    other_session = _chat_session(repository, workspace)

    # Insert out of sequence order with identical created_at timestamps.
    repository.add_messages(
        [
            _message(chat_session, sequence=3, created_at=_NOW),
            _message(chat_session, sequence=1, created_at=_NOW),
            _message(chat_session, sequence=5, created_at=_NOW),
            _message(chat_session, sequence=2, created_at=_NOW),
            _message(chat_session, sequence=4, created_at=_NOW),
            _message(other_session, sequence=1, created_at=_NOW),
        ]
    )

    all_messages = repository.list_messages(chat_session.id)
    assert [msg.sequence for msg in all_messages] == [1, 2, 3, 4, 5]

    recent = repository.list_recent_messages(chat_session.id, limit=3)
    assert [msg.sequence for msg in recent] == [3, 4, 5]

    all_via_recent = repository.list_recent_messages(chat_session.id, limit=10)
    assert [msg.sequence for msg in all_via_recent] == [1, 2, 3, 4, 5]

    assert repository.list_recent_messages(chat_session.id, limit=0) == []
    assert repository.list_recent_messages(chat_session.id, limit=-2) == []


def test_turn_stats_reports_count_and_max_sequence(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    empty_session = _chat_session(repository, workspace)
    active_session = _chat_session(repository, workspace)

    assert repository.turn_stats(empty_session.id) == SessionTurnStats(
        message_count=0, max_sequence=0
    )

    repository.add_messages(
        [_message(active_session, sequence=1), _message(active_session, sequence=2)]
    )
    assert repository.turn_stats(active_session.id) == SessionTurnStats(
        message_count=2, max_sequence=2
    )
    assert repository.turn_stats(empty_session.id) == SessionTurnStats(
        message_count=0, max_sequence=0
    )


def test_existing_document_ids_scopes_to_workspace(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    home = _workspace(db_session, owner, "Home")
    neighbour = _workspace(db_session, owner, "Neighbour")
    doc_a = _document(db_session, home)
    doc_b = _document(db_session, home)
    other_doc = _document(db_session, neighbour)
    missing_id = uuid.uuid4()

    assert repository.existing_document_ids(home.id, []) == set()
    found = repository.existing_document_ids(
        home.id, [doc_a.id, doc_b.id, doc_a.id, other_doc.id, missing_id]
    )
    assert found == {doc_a.id, doc_b.id}


def test_get_for_owner_for_update_refreshes_stale_columns(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner, "Original Name")
    chat_session = _chat_session(repository, workspace, title="Initial Title")

    # Simulate an update bypassing the session identity map (as a concurrent commit would).
    db_session.execute(
        text("UPDATE chat_sessions SET title = :title WHERE id = :id"),
        {"title": "Updated Elsewhere", "id": chat_session.id},
    )
    db_session.execute(
        text("UPDATE workspaces SET name = :name WHERE id = :id"),
        {"name": "Renamed Workspace", "id": workspace.id},
    )
    assert chat_session.title == "Initial Title"

    executed_sql: list[str] = []

    def _capture_sql(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        executed_sql.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", _capture_sql)
    try:
        locked = repository.get_for_owner(chat_session.id, owner.id, for_update=True)
    finally:
        event.remove(connection, "before_cursor_execute", _capture_sql)

    assert locked is not None
    refreshed_session, workspace_name = locked
    assert refreshed_session is chat_session
    assert refreshed_session.title == "Updated Elsewhere"
    assert workspace_name == "Renamed Workspace"
    assert any("FOR UPDATE OF chat_sessions" in sql for sql in executed_sql)


@pytest.mark.usefixtures("_migrated_database")
def test_get_for_owner_for_update_locks_only_chat_sessions_row(database_url: str) -> None:
    engine = get_engine(database_url)
    email = f"lock-{uuid.uuid4()}@example.com"
    owner_id: uuid.UUID | None = None
    try:
        with Session(engine, expire_on_commit=False) as setup:
            owner = _user(setup, email)
            workspace = _workspace(setup, owner, "Concurrency")
            chat_session = _chat_session(ChatRepository(setup), workspace)
            owner_id = owner.id
            workspace_id = workspace.id
            session_id = chat_session.id
            setup.commit()

        with (
            Session(engine, expire_on_commit=False) as holder,
            Session(engine, expire_on_commit=False) as observer,
        ):
            locked = ChatRepository(holder).get_for_owner(session_id, owner_id, for_update=True)
            assert locked is not None

            # Workspaces row stays unlocked so workspaces -> chat_sessions order cannot deadlock.
            unlocked_workspace: uuid.UUID = observer.execute(
                text("SELECT id FROM workspaces WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": workspace_id},
            ).scalar_one()
            assert unlocked_workspace == workspace_id

            with pytest.raises(OperationalError) as caught:
                observer.execute(
                    text("SELECT id FROM chat_sessions WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": session_id},
                )
            assert isinstance(caught.value.orig, psycopg.errors.LockNotAvailable)
            observer.rollback()
            holder.rollback()
    finally:
        if owner_id is not None:
            with Session(engine) as cleanup:
                cleanup.execute(delete(User).where(User.id == owner_id))
                cleanup.commit()


def test_delete_for_owner_cascades_messages_and_handles_missing_rows(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    removed = _chat_session(repository, workspace, title="Removed")
    kept = _chat_session(repository, workspace, title="Kept")
    repository.add_messages(
        [_message(removed, sequence=1), _message(removed, sequence=2), _message(kept, sequence=1)]
    )

    assert repository.delete_for_owner(removed.id, owner.id) is True
    assert repository.delete_for_owner(removed.id, owner.id) is False
    assert repository.delete_for_owner(uuid.uuid4(), owner.id) is False

    assert repository.get_for_owner(removed.id, owner.id) is None
    assert repository.list_messages(removed.id) == []
    assert [msg.sequence for msg in repository.list_messages(kept.id)] == [1]


def test_deleting_workspace_cascades_sessions_and_messages(db_session: Session) -> None:
    repository = ChatRepository(db_session)
    owner = _user(db_session)
    removed_ws = _workspace(db_session, owner, "Removed")
    kept_ws = _workspace(db_session, owner, "Kept")
    removed_session = _chat_session(repository, removed_ws)
    kept_session = _chat_session(repository, kept_ws)
    repository.add_messages(
        [_message(removed_session, sequence=1), _message(kept_session, sequence=1)]
    )

    WorkspaceRepository(db_session).delete(removed_ws)

    assert db_session.scalars(
        select(ChatSession.id).where(ChatSession.id.in_([removed_session.id, kept_session.id]))
    ).all() == [kept_session.id]
    assert db_session.scalars(
        select(ChatMessage.session_id).where(
            ChatMessage.session_id.in_([removed_session.id, kept_session.id])
        )
    ).all() == [kept_session.id]
