import uuid
from collections.abc import Mapping
from typing import Any, Final

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

EMBEDDING_DIMENSIONS: Final = 1536
CHUNK_HEADING_MAX_LENGTH: Final = 500
HNSW_M: Final = 16
HNSW_EF_CONSTRUCTION: Final = 64
# Written exactly as PostgreSQL prints the stored expression back, casts included.
SEARCH_VECTOR_EXPRESSION: Final = (
    "to_tsvector('simple'::regconfig, coalesce(heading, ''::character varying)::text"
    " || ' '::text || content)"
)


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_id_chunk_index"
        ),
        Index("ix_document_chunks_workspace_id", "workspace_id"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": HNSW_M, "ef_construction": HNSW_EF_CONSTRUCTION},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_document_chunks_search_vector", "search_vector", postgresql_using="gin"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint("char_count > 0", name="char_count_positive"),
        # Both bounds or neither: a comparison with NULL passes a CHECK, so without the
        # first clause a range with only one bound would be accepted.
        CheckConstraint(
            "(page_start IS NULL) = (page_end IS NULL)"
            " AND (page_start IS NULL OR (page_start >= 1 AND page_end >= page_start))",
            name="page_range_valid",
        ),
    )
    # Chunks are bulk-inserted; fetching every generated tsvector back is wasted work.
    __mapper_args__: Mapping[str, Any] = {"eager_defaults": False}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(CHUNK_HEADING_MAX_LENGTH), default=None)
    page_start: Mapped[int | None] = mapped_column(Integer, default=None)
    page_end: Mapped[int | None] = mapped_column(Integer, default=None)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR_EXPRESSION, persisted=True), deferred=True
    )
