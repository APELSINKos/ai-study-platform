import uuid
from http import HTTPStatus
from typing import Annotated, Final

from fastapi import APIRouter, Query

from app.api.deps import ChatServiceDep, CurrentUser, RedisClient, SettingsDep
from app.api.errors import error_responses
from app.api.pagination import PageParamsDep
from app.core.rate_limit import RateLimit, enforce_rate_limit, rate_limit_key
from app.models.chat_message import ChatMessage
from app.repositories.chat import ChatSessionSummary
from app.schemas.chat import (
    ChatMessageCreateRequest,
    ChatMessageOut,
    ChatSessionCreateRequest,
    ChatSessionDetailOut,
    ChatSessionOut,
    ChatSessionPage,
    ChatSessionUpdateRequest,
    ChatTurnOut,
    CitationOut,
)

_MINUTE_SECONDS: Final = 60
_CHAT_RATE_LIMIT_SCOPE: Final = "chat_user"

router = APIRouter(prefix="/chat", tags=["chat"])


def _session_out(summary: ChatSessionSummary) -> ChatSessionOut:
    session = summary.session
    return ChatSessionOut(
        id=session.id,
        workspace_id=session.workspace_id,
        workspace_name=summary.workspace_name,
        title=session.title,
        document_ids=list(session.document_ids) if session.document_ids is not None else None,
        message_count=summary.message_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _message_out(message: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(
        id=message.id,
        sequence=message.sequence,
        role=message.role,
        content=message.content,
        citations=[CitationOut.model_validate(item) for item in message.citations],
        insufficient_context=message.insufficient_context,
        model=message.model,
        retrieval_ms=message.retrieval_ms,
        generation_ms=message.generation_ms,
        prompt_tokens=message.prompt_tokens,
        completion_tokens=message.completion_tokens,
        created_at=message.created_at,
    )


@router.get(
    "/sessions",
    summary="List your chat sessions, the most recently updated first",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND),
)
def list_chat_sessions(
    current_user: CurrentUser,
    service: ChatServiceDep,
    page: PageParamsDep,
    workspace_id: Annotated[
        uuid.UUID | None, Query(description="Only sessions in this workspace.")
    ] = None,
) -> ChatSessionPage:
    items, total = service.list_sessions(
        user=current_user,
        workspace_id=workspace_id,
        offset=page.offset,
        limit=page.limit,
    )
    return ChatSessionPage(
        items=[_session_out(item) for item in items],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post(
    "/sessions",
    status_code=HTTPStatus.CREATED,
    summary="Create a chat session scoped to a workspace or selected documents",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND),
)
def create_chat_session(
    payload: ChatSessionCreateRequest,
    current_user: CurrentUser,
    service: ChatServiceDep,
) -> ChatSessionOut:
    return _session_out(service.create_session(user=current_user, request=payload))


@router.get(
    "/sessions/{session_id}",
    summary="Get a chat session with all of its messages in chronological order",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND),
)
def get_chat_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    service: ChatServiceDep,
) -> ChatSessionDetailOut:
    summary, messages = service.get_session(user=current_user, session_id=session_id)
    base = _session_out(summary)
    return ChatSessionDetailOut(
        **base.model_dump(),
        messages=[_message_out(message) for message in messages],
    )


@router.patch(
    "/sessions/{session_id}",
    summary="Rename a chat session or change its document scope",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND),
)
def update_chat_session(
    session_id: uuid.UUID,
    payload: ChatSessionUpdateRequest,
    current_user: CurrentUser,
    service: ChatServiceDep,
) -> ChatSessionOut:
    return _session_out(
        service.update_session(user=current_user, session_id=session_id, changes=payload)
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete a chat session and all of its messages",
    responses=error_responses(HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND),
)
def delete_chat_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    service: ChatServiceDep,
) -> None:
    service.delete_session(user=current_user, session_id=session_id)


@router.post(
    "/sessions/{session_id}/messages",
    status_code=HTTPStatus.CREATED,
    summary="Send a question and receive a grounded answer with citations",
    responses=error_responses(
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
        HTTPStatus.CONFLICT,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.SERVICE_UNAVAILABLE,
    ),
)
def send_chat_message(  # noqa: PLR0913, PLR0917 -- FastAPI dependency injection, not real complexity
    session_id: uuid.UUID,
    payload: ChatMessageCreateRequest,
    current_user: CurrentUser,
    service: ChatServiceDep,
    settings: SettingsDep,
    redis: RedisClient,
) -> ChatTurnOut:
    """Rate-limited per signed-in user before session ownership is checked. When no relevant
    passages are found, the chat model is skipped and the reply reports insufficient context."""
    rule = RateLimit(_CHAT_RATE_LIMIT_SCOPE, settings.chat_messages_per_minute, _MINUTE_SECONDS)
    enforce_rate_limit(redis, rule, rate_limit_key(str(current_user.id)))
    summary, user_message, assistant_message = service.send_message(
        user=current_user,
        session_id=session_id,
        content=payload.content,
    )
    return ChatTurnOut(
        session=_session_out(summary),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant_message),
    )
