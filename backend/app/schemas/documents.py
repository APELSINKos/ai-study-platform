import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.api.pagination import Page
from app.models.document import (
    Difficulty,
    DocumentContentType,
    DocumentErrorCode,
    DocumentStatus,
)


class DocumentOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    original_filename: str
    content_type: DocumentContentType
    size_bytes: int
    status: DocumentStatus
    error_code: DocumentErrorCode | None = Field(
        description="Why processing failed. While an automatic retry is pending the status"
        " is uploaded and the code ai_unavailable."
    )
    attempts: int = Field(description="Processing runs started so far.")
    title: str | None
    summary: str | None
    topics: list[str] | None
    difficulty: Difficulty | None
    estimated_study_minutes: int | None
    page_count: int | None
    word_count: int | None
    chunk_count: int | None
    analysis_model: str | None
    embedding_model: str | None
    processing_ms: int | None
    processing_started_at: datetime | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    can_retry: bool = Field(
        description="Whether processing can be started again: the document failed, or its"
        " status has not changed for too long."
    )


class DocumentPage(Page[DocumentOut]):
    pass
