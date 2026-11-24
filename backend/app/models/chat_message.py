import uuid
from typing import Final, Literal, get_args

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.document import MODEL_NAME_MAX_LENGTH

type ChatMessageRole = Literal["user", "assistant"]

CHAT_MESSAGE_ROLE_VALUES: Final[tuple[ChatMessageRole, ...]] = get_args(ChatMessageRole.__value__)
CHAT_MESSAGE_ROLE_MAX_LENGTH: Final = 16


def _one_of(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class ChatMessage(TimestampMixin, Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_chat_messages_session_id_sequence"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(_one_of("role", CHAT_MESSAGE_ROLE_VALUES), name="role_valid"),
        CheckConstraint("content <> ''", name="content_non_empty"),
        CheckConstraint("jsonb_typeof(citations) = 'array'", name="citations_is_array"),
        CheckConstraint(
            "NOT insufficient_context OR jsonb_array_length(citations) = 0",
            name="insufficient_context_no_citations",
        ),
        CheckConstraint(
            "retrieval_ms IS NULL OR retrieval_ms >= 0", name="retrieval_ms_non_negative"
        ),
        CheckConstraint(
            "generation_ms IS NULL OR generation_ms >= 0", name="generation_ms_non_negative"
        ),
        CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0", name="prompt_tokens_non_negative"
        ),
        CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name="completion_tokens_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[ChatMessageRole] = mapped_column(
        String(CHAT_MESSAGE_ROLE_MAX_LENGTH), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB(none_as_null=True), nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    insufficient_context: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    model: Mapped[str | None] = mapped_column(String(MODEL_NAME_MAX_LENGTH), default=None)
    retrieval_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    generation_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
