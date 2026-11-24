import uuid
from datetime import datetime
from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, StringConstraints

from app.api.pagination import Page
from app.documents.chunking import HEADING_SEPARATOR
from app.documents.cleaning import clean_text
from app.models.chat_message import ChatMessageRole
from app.models.chat_session import CHAT_SESSION_TITLE_MAX_LENGTH, MAX_SCOPE_DOCUMENTS
from app.rag.citations import clean_chat_text
from app.schemas.text import reject_nul

CHAT_MESSAGE_MAX_CHARS: Final = 2000
MAX_MESSAGES_PER_SESSION: Final = 200
AUTO_TITLE_MAX_CHARS: Final = 80
_MESSAGE_MIN_CHARS: Final = 1
_SCOPE_MIN_DOCUMENTS: Final = 1
_EMPTY_CLEANED_MESSAGE: Final = "The message must contain readable text."


def _sanitize_title(value: object) -> object:
    if not isinstance(value, str):
        return value
    reject_nul(value)
    return " ".join(clean_chat_text(value).split())


def _blank_as_none(value: str | None) -> str | None:
    return value or None


def _dedupe_uuids(values: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(values))


def _require_cleaned_text(value: str) -> str:
    # Static message: never echo untrusted input into validation error details.
    if not clean_chat_text(value) or not " ".join(clean_text(value).split()):
        raise ValueError(_EMPTY_CLEANED_MESSAGE)
    return value


_TitleText = Annotated[
    str,
    BeforeValidator(_sanitize_title),
    StringConstraints(strip_whitespace=True, max_length=CHAT_SESSION_TITLE_MAX_LENGTH),
]
# A blank title is stored as untitled (None) and auto-filled on the first message.
ChatSessionTitle = Annotated[_TitleText | None, AfterValidator(_blank_as_none)]

ScopeDocumentIds = Annotated[
    list[uuid.UUID],
    Field(min_length=_SCOPE_MIN_DOCUMENTS, max_length=MAX_SCOPE_DOCUMENTS),
    AfterValidator(_dedupe_uuids),
]


class ChatSessionCreateRequest(BaseModel):
    workspace_id: uuid.UUID
    title: ChatSessionTitle = None
    document_ids: ScopeDocumentIds | None = None


class ChatSessionUpdateRequest(BaseModel):
    """Only the fields sent change; null clears the title or resets the document scope."""

    title: ChatSessionTitle = None
    document_ids: ScopeDocumentIds | None = None


class ChatMessageCreateRequest(BaseModel):
    content: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=_MESSAGE_MIN_CHARS,
            max_length=CHAT_MESSAGE_MAX_CHARS,
        ),
        AfterValidator(reject_nul),
        AfterValidator(_require_cleaned_text),
    ]


class CitationOut(BaseModel):
    index: int = Field(description="1-based display citation index matching [1], [2] in content.")
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str = Field(
        description="Snapshot of the document title or file name at answer time."
    )
    chunk_index: int = Field(description="Position of the cited passage in its document, from 0.")
    heading: str | None = Field(
        description="The headings above the passage, outermost first, joined with"
        f" '{HEADING_SEPARATOR}'."
    )
    page_start: int | None = Field(
        description="First PDF page of the passage; null for text files."
    )
    page_end: int | None = Field(description="Last PDF page of the passage; null for text files.")
    quote: str = Field(description="Immutable plain-text excerpt of the cited passage.")


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    sequence: int = Field(description="1-based chronological order within the session.")
    role: ChatMessageRole
    content: str
    citations: list[CitationOut]
    insufficient_context: bool = Field(
        description="True when retrieved passages did not cover the question."
    )
    model: str | None = Field(
        description="Chat model that wrote the answer; null for user messages or skipped LLM turns."
    )
    retrieval_ms: int | None = Field(
        description="Milliseconds spent retrieving passages; null for user messages."
    )
    generation_ms: int | None = Field(
        description="Milliseconds spent waiting on the chat model; null for user messages."
    )
    prompt_tokens: int | None = Field(
        description="Prompt tokens reported by the chat model; null when the model was not called."
    )
    completion_tokens: int | None = Field(
        description="Completion tokens reported by the chat model; null when the model was not"
        " called."
    )
    created_at: datetime


class ChatSessionOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_name: str
    title: str | None
    document_ids: list[uuid.UUID] | None = Field(
        description="Document IDs this session is narrowed to; null covers the whole workspace."
    )
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatSessionPage(Page[ChatSessionOut]):
    pass


class ChatSessionDetailOut(ChatSessionOut):
    messages: list[ChatMessageOut]


class ChatTurnOut(BaseModel):
    session: ChatSessionOut
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
