import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, delete, exists, func, select, true
from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.workspace import Workspace


@dataclass(frozen=True, slots=True)
class ChatSessionSummary:
    session: ChatSession
    workspace_name: str
    message_count: int


@dataclass(frozen=True, slots=True)
class SessionTurnStats:
    message_count: int
    max_sequence: int


class ChatRepository:
    """Direct database access for chat sessions and messages. Never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_session(self, session: ChatSession) -> ChatSession:
        self._session.add(session)
        self._session.flush()
        return session

    def add_messages(self, messages: Sequence[ChatMessage]) -> None:
        if not messages:
            return
        self._session.add_all(messages)
        self._session.flush()

    def get_for_owner(
        self, session_id: uuid.UUID, owner_id: uuid.UUID, *, for_update: bool = False
    ) -> tuple[ChatSession, str] | None:
        statement = (
            select(ChatSession, Workspace.name)
            .join(Workspace, Workspace.id == ChatSession.workspace_id)
            .where(
                ChatSession.id == session_id,
                ChatSession.user_id == owner_id,
                Workspace.owner_id == owner_id,
            )
        )
        if for_update:
            # Lock only chat_sessions (never workspaces) to preserve workspaces ->
            # chat_sessions lock order, and reload columns even with expire_on_commit=False.
            statement = statement.with_for_update(of=ChatSession).execution_options(
                populate_existing=True
            )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    def list_for_owner(
        self,
        owner_id: uuid.UUID,
        offset: int,
        limit: int,
        *,
        workspace_id: uuid.UUID | None = None,
    ) -> tuple[list[ChatSessionSummary], int]:
        criteria: list[ColumnElement[bool]] = [
            ChatSession.user_id == owner_id,
            Workspace.owner_id == owner_id,
        ]
        if workspace_id is not None:
            criteria.append(ChatSession.workspace_id == workspace_id)
        # LATERAL counts messages only for the sessions on the requested page.
        counts = (
            select(func.count().label("message_count"))
            .where(ChatMessage.session_id == ChatSession.id)
            .lateral("session_message_counts")
        )
        statement = (
            select(ChatSession, Workspace.name.label("workspace_name"), counts.c.message_count)
            .join(Workspace, Workspace.id == ChatSession.workspace_id)
            .join(counts, true())
            .where(*criteria)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            .offset(offset)
            .limit(limit)
        )
        items = [
            ChatSessionSummary(
                session=row[0],
                workspace_name=row[1],
                message_count=row[2],
            )
            for row in self._session.execute(statement)
        ]
        total_statement = (
            select(func.count())
            .select_from(ChatSession)
            .join(Workspace, Workspace.id == ChatSession.workspace_id)
            .where(*criteria)
        )
        return items, self._session.execute(total_statement).scalar_one()

    def list_messages(self, session_id: uuid.UUID) -> list[ChatMessage]:
        statement = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.asc())
        )
        return list(self._session.execute(statement).scalars())

    def list_recent_messages(self, session_id: uuid.UUID, limit: int) -> list[ChatMessage]:
        if limit <= 0:
            return []
        statement = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(limit)
        )
        recent = list(self._session.execute(statement).scalars())
        recent.reverse()
        return recent

    def turn_stats(self, session_id: uuid.UUID) -> SessionTurnStats:
        statement = select(
            func.count(),
            func.coalesce(func.max(ChatMessage.sequence), 0),
        ).where(ChatMessage.session_id == session_id)
        message_count, max_sequence = self._session.execute(statement).one()
        return SessionTurnStats(message_count=message_count, max_sequence=max_sequence)

    def existing_document_ids(
        self, workspace_id: uuid.UUID, document_ids: Sequence[uuid.UUID]
    ) -> set[uuid.UUID]:
        if not document_ids:
            return set()
        statement = select(Document.id).where(
            Document.workspace_id == workspace_id,
            Document.id.in_(list(dict.fromkeys(document_ids))),
        )
        return set(self._session.execute(statement).scalars())

    def delete_for_owner(self, session_id: uuid.UUID, owner_id: uuid.UUID) -> bool:
        owns_workspace = exists(
            select(1).where(
                Workspace.id == ChatSession.workspace_id,
                Workspace.owner_id == owner_id,
            )
        )
        statement = (
            delete(ChatSession)
            .where(
                ChatSession.id == session_id,
                ChatSession.user_id == owner_id,
                owns_workspace,
            )
            .returning(ChatSession.id)
        )
        return self._session.execute(statement).first() is not None
