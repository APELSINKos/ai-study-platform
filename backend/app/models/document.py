import uuid
from datetime import datetime
from typing import Final, Literal, get_args

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

type DocumentStatus = Literal["uploaded", "processing", "indexing", "ready", "failed"]
type DocumentContentType = Literal["application/pdf", "text/markdown", "text/plain"]
type Difficulty = Literal["easy", "medium", "hard"]
type DocumentErrorCode = Literal[
    "pdf_unreadable",
    "pdf_encrypted",
    "no_text",
    "too_many_pages",
    "text_too_long",
    "file_missing",
    "ai_unavailable",
    "ai_quota_exceeded",
    "ai_rejected",
    "ai_invalid_output",
    "embedding_dimension_mismatch",
    "processing_timeout",
    "queue_unavailable",
    "internal_error",
]

DOCUMENT_STATUSES: Final[tuple[DocumentStatus, ...]] = get_args(DocumentStatus.__value__)
DOCUMENT_CONTENT_TYPES: Final[tuple[DocumentContentType, ...]] = get_args(
    DocumentContentType.__value__
)
DIFFICULTIES: Final[tuple[Difficulty, ...]] = get_args(Difficulty.__value__)
DOCUMENT_ERROR_CODES: Final[tuple[DocumentErrorCode, ...]] = get_args(DocumentErrorCode.__value__)
# Statuses of a document that is still waiting for, or going through, processing.
ACTIVE_DOCUMENT_STATUSES: Final[tuple[DocumentStatus, ...]] = (
    "uploaded",
    "processing",
    "indexing",
)

ORIGINAL_FILENAME_MAX_LENGTH: Final = 255
CONTENT_TYPE_MAX_LENGTH: Final = 64
SHA256_HEX_LENGTH: Final = 64
STORAGE_KEY_MAX_LENGTH: Final = 255
STATUS_MAX_LENGTH: Final = 16
ERROR_CODE_MAX_LENGTH: Final = 64
ERROR_MESSAGE_MAX_LENGTH: Final = 500
TITLE_MAX_LENGTH: Final = 200
SUMMARY_MAX_LENGTH: Final = 1000
DIFFICULTY_MAX_LENGTH: Final = 16
MODEL_NAME_MAX_LENGTH: Final = 100


def _one_of(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sha256", name="uq_documents_workspace_id_sha256"),
        # The target of the chunks' composite foreign key, which keeps a chunk in the
        # same workspace as its document.
        UniqueConstraint("id", "workspace_id", name="uq_documents_id_workspace_id"),
        Index("ix_documents_workspace_id_created_at", "workspace_id", "created_at"),
        CheckConstraint(_one_of("status", DOCUMENT_STATUSES), name="status_valid"),
        CheckConstraint(_one_of("content_type", DOCUMENT_CONTENT_TYPES), name="content_type_valid"),
        CheckConstraint(_one_of("difficulty", DIFFICULTIES), name="difficulty_valid"),
        CheckConstraint(_one_of("error_code", DOCUMENT_ERROR_CODES), name="error_code_valid"),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("topics IS NULL OR jsonb_typeof(topics) = 'array'", name="topics_array"),
        CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL", name="failed_has_error_code"
        ),
        CheckConstraint(
            "status <> 'ready' OR (chunk_count IS NOT NULL AND embedding_model IS NOT NULL"
            " AND processed_at IS NOT NULL)",
            name="ready_is_complete",
        ),
        CheckConstraint(
            "page_count >= 0 AND word_count >= 0 AND chunk_count >= 0"
            " AND processing_ms >= 0 AND estimated_study_minutes >= 0",
            name="counts_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(
        String(ORIGINAL_FILENAME_MAX_LENGTH), nullable=False
    )
    content_type: Mapped[DocumentContentType] = mapped_column(
        String(CONTENT_TYPE_MAX_LENGTH), nullable=False
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), nullable=False)
    storage_key: Mapped[str] = mapped_column(
        String(STORAGE_KEY_MAX_LENGTH), unique=True, nullable=False
    )
    status: Mapped[DocumentStatus] = mapped_column(
        String(STATUS_MAX_LENGTH), nullable=False, default="uploaded", server_default="uploaded"
    )
    error_code: Mapped[DocumentErrorCode | None] = mapped_column(
        String(ERROR_CODE_MAX_LENGTH), default=None
    )
    error_message: Mapped[str | None] = mapped_column(
        String(ERROR_MESSAGE_MAX_LENGTH), default=None
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    title: Mapped[str | None] = mapped_column(String(TITLE_MAX_LENGTH), default=None)
    summary: Mapped[str | None] = mapped_column(String(SUMMARY_MAX_LENGTH), default=None)
    topics: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    difficulty: Mapped[Difficulty | None] = mapped_column(
        String(DIFFICULTY_MAX_LENGTH), default=None
    )
    estimated_study_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    page_count: Mapped[int | None] = mapped_column(Integer, default=None)
    word_count: Mapped[int | None] = mapped_column(Integer, default=None)
    chunk_count: Mapped[int | None] = mapped_column(Integer, default=None)
    processing_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    analysis_model: Mapped[str | None] = mapped_column(String(MODEL_NAME_MAX_LENGTH), default=None)
    embedding_model: Mapped[str | None] = mapped_column(String(MODEL_NAME_MAX_LENGTH), default=None)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
