"""workspaces documents chunks

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 11:57:55.757557

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_workspaces_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.create_index(
        "ix_workspaces_owner_id_updated_at", "workspaces", ["owner_id", "updated_at"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="uploaded", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.String(length=1000), nullable=True),
        sa.Column("topics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("difficulty", sa.String(length=16), nullable=True),
        sa.Column("estimated_study_minutes", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=True),
        sa.Column("analysis_model", sa.String(length=100), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'text/markdown', 'text/plain')",
            name=op.f("ck_documents_content_type_valid"),
        ),
        sa.CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')", name=op.f("ck_documents_difficulty_valid")
        ),
        sa.CheckConstraint(
            "error_code IN ('pdf_unreadable', 'pdf_encrypted', 'no_text', 'too_many_pages',"
            " 'text_too_long', 'file_missing', 'ai_unavailable', 'ai_quota_exceeded',"
            " 'ai_rejected', 'ai_invalid_output', 'embedding_dimension_mismatch',"
            " 'processing_timeout', 'queue_unavailable', 'internal_error')",
            name=op.f("ck_documents_error_code_valid"),
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_documents_sha256_hex")),
        sa.CheckConstraint(
            "status <> 'failed' OR error_code IS NOT NULL",
            name=op.f("ck_documents_failed_has_error_code"),
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR (chunk_count IS NOT NULL AND embedding_model IS NOT NULL"
            " AND processed_at IS NOT NULL)",
            name=op.f("ck_documents_ready_is_complete"),
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'indexing', 'ready', 'failed')",
            name=op.f("ck_documents_status_valid"),
        ),
        sa.CheckConstraint(
            "topics IS NULL OR jsonb_typeof(topics) = 'array'",
            name=op.f("ck_documents_topics_array"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_documents_attempts_non_negative")),
        sa.CheckConstraint(
            "page_count >= 0 AND word_count >= 0 AND chunk_count >= 0"
            " AND processing_ms >= 0 AND estimated_study_minutes >= 0",
            name=op.f("ck_documents_counts_non_negative"),
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_documents_size_bytes_positive")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_documents_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("id", "workspace_id", name="uq_documents_id_workspace_id"),
        sa.UniqueConstraint("storage_key", name=op.f("uq_documents_storage_key")),
        sa.UniqueConstraint("workspace_id", "sha256", name="uq_documents_workspace_id_sha256"),
    )
    op.create_index(
        "ix_documents_workspace_id_created_at",
        "documents",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, coalesce(heading, ''::character varying)::text"
                " || ' '::text || content)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(page_start IS NULL) = (page_end IS NULL)"
            " AND (page_start IS NULL OR (page_start >= 1 AND page_end >= page_start))",
            name=op.f("ck_document_chunks_page_range_valid"),
        ),
        sa.CheckConstraint("char_count > 0", name=op.f("ck_document_chunks_char_count_positive")),
        sa.CheckConstraint(
            "chunk_index >= 0", name=op.f("ck_document_chunks_chunk_index_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_document_chunks_document_id_chunk_index"
        ),
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_document_chunks_workspace_id", "document_chunks", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_document_chunks_workspace_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_search_vector", table_name="document_chunks")
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_workspace_id_created_at", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_workspaces_owner_id_updated_at", table_name="workspaces")
    op.drop_table("workspaces")
