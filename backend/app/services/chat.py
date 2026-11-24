"""Chat session lifecycle and grounded RAG Q&A turns.

Each chat turn uses three short database transactions so no connection or row lock is held
while waiting on external embedding or chat models:
  Tx 1 (read): verify ownership, enforce message limit, read document scope and recent history.
  Tx 2 (read, inside RAGService): retrieve ranked passages, then commit before calling the LLM.
  Tx 3 (write): lock workspaces -> chat_sessions in cascade-safe order, re-check limit, persist.
"""

import math
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Final

import psycopg
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.documents.text import shorten
from app.llm.base import (
    ChatHistoryTurn,
    EmbeddingProvider,
    LLMProvider,
    ProviderError,
    ProviderUnavailableError,
)
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.user import User
from app.rag.citations import clean_chat_text
from app.rag.service import RAGService
from app.rag.vector_store import VectorStore
from app.repositories.chat import ChatRepository, ChatSessionSummary
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.chat import (
    AUTO_TITLE_MAX_CHARS,
    MAX_MESSAGES_PER_SESSION,
    ChatSessionCreateRequest,
    ChatSessionUpdateRequest,
)
from app.services.documents import document_not_found
from app.services.workspaces import workspace_not_found

logger = structlog.get_logger(__name__)

MESSAGES_PER_TURN: Final = 2
MAX_HISTORY_TURNS: Final = 3
MIN_CHAT_RETRY_AFTER_SECONDS: Final = 1
DEFAULT_CHAT_RETRY_AFTER_SECONDS: Final = 30
MAX_CHAT_RETRY_AFTER_SECONDS: Final = 300
CHAT_WORKSPACE_FOREIGN_KEY: Final = "fk_chat_sessions_workspace_id_workspaces"

_CHAT_SESSION_NOT_FOUND_MESSAGE: Final = "The chat session was not found."
_CHAT_SESSION_LIMIT_MESSAGE: Final = "This chat session has reached the maximum number of messages."
_CHAT_UNAVAILABLE_MESSAGE: Final = (
    "The AI chat service is temporarily unavailable. Try again later."
)
_CHAT_QUOTA_EXCEEDED_MESSAGE: Final = "The AI provider quota has been exceeded."


def chat_session_not_found() -> NotFoundError:
    """The error for a chat session that does not exist or belongs to another user."""
    return NotFoundError(_CHAT_SESSION_NOT_FOUND_MESSAGE, code="chat_session_not_found")


def chat_session_limit_reached() -> ConflictError:
    """The error when a chat session cannot hold another user/assistant turn."""
    return ConflictError(_CHAT_SESSION_LIMIT_MESSAGE, code="chat_session_limit_reached")


def _violated_constraint(error: IntegrityError) -> str | None:
    if isinstance(error.orig, psycopg.Error):
        return error.orig.diag.constraint_name
    return None


def _clamped_retry_after(retry_after_seconds: float | None) -> int:
    if retry_after_seconds is None or not math.isfinite(retry_after_seconds):
        return DEFAULT_CHAT_RETRY_AFTER_SECONDS
    seconds = math.ceil(retry_after_seconds)
    return max(MIN_CHAT_RETRY_AFTER_SECONDS, min(MAX_CHAT_RETRY_AFTER_SECONDS, seconds))


def _chat_provider_error(error: ProviderError) -> ServiceUnavailableError:
    if isinstance(error, ProviderUnavailableError):
        retry_after = _clamped_retry_after(error.retry_after_seconds)
        return ServiceUnavailableError(
            _CHAT_UNAVAILABLE_MESSAGE,
            code="chat_unavailable",
            headers={"Retry-After": str(retry_after)},
        )
    if error.code == "ai_quota_exceeded":
        return ServiceUnavailableError(_CHAT_QUOTA_EXCEEDED_MESSAGE, code="chat_quota_exceeded")
    return ServiceUnavailableError(_CHAT_UNAVAILABLE_MESSAGE, code="chat_unavailable")


def _auto_title(content: str) -> str:
    return shorten(" ".join(content.split()), AUTO_TITLE_MAX_CHARS)


class ChatService:
    """Manages a user's chat sessions and runs grounded Q&A turns over workspace materials."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        embedder: EmbeddingProvider,
        llm: LLMProvider,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._clock = clock
        self._chat = ChatRepository(session)
        self._workspaces = WorkspaceRepository(session)
        self._store = VectorStore(session)
        self._rag = RAGService(
            self._store,
            embedder,
            llm,
            embedding_model=embedder.model_name,
            min_similarity=settings.search_min_similarity,
            turn_timeout_seconds=(
                settings.chat_embedding_timeout_seconds + settings.chat_llm_timeout_seconds
            ),
        )

    def list_sessions(
        self,
        *,
        user: User,
        workspace_id: uuid.UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ChatSessionSummary], int]:
        if (
            workspace_id is not None
            and self._workspaces.get_for_owner(workspace_id, user.id) is None
        ):
            raise workspace_not_found()
        return self._chat.list_for_owner(user.id, offset, limit, workspace_id=workspace_id)

    def create_session(
        self, *, user: User, request: ChatSessionCreateRequest
    ) -> ChatSessionSummary:
        workspace = self._workspaces.get_for_owner(request.workspace_id, user.id)
        if workspace is None:
            raise workspace_not_found()
        if request.document_ids is not None:
            self._require_workspace_documents(request.workspace_id, request.document_ids)
        now = self._clock()
        chat_session = ChatSession(
            workspace_id=request.workspace_id,
            user_id=user.id,
            title=request.title,
            document_ids=list(request.document_ids) if request.document_ids is not None else None,
            created_at=now,
            updated_at=now,
        )
        try:
            self._chat.add_session(chat_session)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            if _violated_constraint(exc) == CHAT_WORKSPACE_FOREIGN_KEY:
                raise workspace_not_found() from exc
            raise
        return ChatSessionSummary(
            session=chat_session,
            workspace_name=workspace.name,
            message_count=0,
        )

    def get_session(
        self, *, user: User, session_id: uuid.UUID
    ) -> tuple[ChatSessionSummary, list[ChatMessage]]:
        found = self._chat.get_for_owner(session_id, user.id)
        if found is None:
            raise chat_session_not_found()
        chat_session, workspace_name = found
        messages = self._chat.list_messages(chat_session.id)
        summary = ChatSessionSummary(
            session=chat_session,
            workspace_name=workspace_name,
            message_count=len(messages),
        )
        return summary, messages

    def update_session(
        self,
        *,
        user: User,
        session_id: uuid.UUID,
        changes: ChatSessionUpdateRequest,
    ) -> ChatSessionSummary:
        found = self._chat.get_for_owner(session_id, user.id, for_update=True)
        if found is None:
            raise chat_session_not_found()
        chat_session, workspace_name = found
        sent = changes.model_fields_set
        if "title" in sent:
            chat_session.title = changes.title
        if "document_ids" in sent:
            if changes.document_ids is not None:
                try:
                    self._require_workspace_documents(
                        chat_session.workspace_id, changes.document_ids
                    )
                except NotFoundError:
                    self._session.rollback()
                    raise
                chat_session.document_ids = list(changes.document_ids)
            else:
                chat_session.document_ids = None
        chat_session.updated_at = self._clock()
        stats = self._chat.turn_stats(chat_session.id)
        self._session.commit()
        return ChatSessionSummary(
            session=chat_session,
            workspace_name=workspace_name,
            message_count=stats.message_count,
        )

    def delete_session(self, *, user: User, session_id: uuid.UUID) -> None:
        if not self._chat.delete_for_owner(session_id, user.id):
            raise chat_session_not_found()
        self._session.commit()

    def send_message(
        self, *, user: User, session_id: uuid.UUID, content: str
    ) -> tuple[ChatSessionSummary, ChatMessage, ChatMessage]:
        # Tx 1 (read): ownership, turn cap, document scope and recent conversation history.
        found = self._chat.get_for_owner(session_id, user.id)
        if found is None:
            raise chat_session_not_found()
        chat_session, _ = found
        stats = self._chat.turn_stats(chat_session.id)
        if stats.message_count + MESSAGES_PER_TURN > MAX_MESSAGES_PER_SESSION:
            raise chat_session_limit_reached()

        user_id = user.id
        workspace_id = chat_session.workspace_id
        document_ids = (
            list(chat_session.document_ids) if chat_session.document_ids is not None else None
        )
        scope = self._store.scope(
            workspace_id,
            embedding_model=self._embedder.model_name,
            document_ids=document_ids,
        )
        recent = self._chat.list_recent_messages(
            chat_session.id, MESSAGES_PER_TURN * MAX_HISTORY_TURNS
        )
        history = tuple(ChatHistoryTurn(role=msg.role, content=msg.content) for msg in recent)
        # commit() rather than rollback() keeps loaded ORM rows (including user) unexpired while
        # releasing the read transaction before calling external AI models.
        self._session.commit()

        cleaned_content = clean_chat_text(content)

        # RAG phase (external embedding + Tx 2 retrieval + external LLM).
        try:
            rag = self._rag.answer(
                workspace_id,
                cleaned_content,
                document_ids=document_ids,
                history=history,
                scope=scope,
                end_read_tx=self._session.commit,
            )
        except ProviderError as error:
            logger.warning(
                "chat_generation_failed",
                session_id=str(session_id),
                workspace_id=str(workspace_id),
                error_code=error.code,
            )
            raise _chat_provider_error(error) from error

        # Tx 3 (write): lock workspaces before chat_sessions to match workspace delete cascade.
        now = self._clock()
        self._workspaces.touch(workspace_id, now)
        locked = self._chat.get_for_owner(session_id, user_id, for_update=True)
        if locked is None:
            self._session.rollback()
            raise chat_session_not_found()
        locked_session, workspace_name = locked
        locked_stats = self._chat.turn_stats(locked_session.id)
        if locked_stats.message_count + MESSAGES_PER_TURN > MAX_MESSAGES_PER_SESSION:
            self._session.rollback()
            raise chat_session_limit_reached()

        retrieval_ms = max(0, round(rag.retrieval_ms))
        generation_ms = max(0, round(rag.generation_ms))
        user_message = ChatMessage(
            session_id=locked_session.id,
            sequence=locked_stats.max_sequence + 1,
            role="user",
            content=cleaned_content,
            citations=[],
            insufficient_context=False,
            model=None,
            retrieval_ms=None,
            generation_ms=None,
            prompt_tokens=None,
            completion_tokens=None,
            created_at=now,
        )
        assistant_message = ChatMessage(
            session_id=locked_session.id,
            sequence=locked_stats.max_sequence + MESSAGES_PER_TURN,
            role="assistant",
            content=rag.content,
            citations=[citation.to_json() for citation in rag.citations],
            insufficient_context=rag.insufficient_context,
            model=rag.model,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            prompt_tokens=None if rag.skipped_llm else rag.prompt_tokens,
            completion_tokens=None if rag.skipped_llm else rag.completion_tokens,
            created_at=now,
        )
        if locked_session.title is None:
            locked_session.title = _auto_title(cleaned_content)
        locked_session.updated_at = now
        self._chat.add_messages([user_message, assistant_message])
        self._session.commit()

        logger.info(
            "chat_turn_completed",
            session_id=str(locked_session.id),
            workspace_id=str(workspace_id),
            chunk_count=len(rag.retrieved_chunks),
            citation_count=len(rag.citations),
            insufficient_context=rag.insufficient_context,
            grounding_overridden=rag.grounding_overridden,
            semantic_available=rag.semantic_available,
            skipped_llm=rag.skipped_llm,
            model=rag.model,
            embedding_ms=rag.embedding_ms,
            retrieval_ms=rag.retrieval_ms,
            generation_ms=rag.generation_ms,
            prompt_tokens=assistant_message.prompt_tokens,
            completion_tokens=assistant_message.completion_tokens,
            question_chars=len(cleaned_content),
            answer_chars=len(rag.content),
        )
        summary = ChatSessionSummary(
            session=locked_session,
            workspace_name=workspace_name,
            message_count=locked_stats.message_count + MESSAGES_PER_TURN,
        )
        return summary, user_message, assistant_message

    def _require_workspace_documents(
        self, workspace_id: uuid.UUID, document_ids: list[uuid.UUID]
    ) -> None:
        existing = self._chat.existing_document_ids(workspace_id, document_ids)
        if len(existing) != len(set(document_ids)):
            raise document_not_found()
