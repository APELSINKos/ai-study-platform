"""chat sessions and messages

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint("uq_workspaces_id_owner_id", "workspaces", ["id", "owner_id"])
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("document_ids", postgresql.ARRAY(sa.Uuid()), nullable=True),
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
            "document_ids IS NULL OR ("
            "array_ndims(document_ids) = 1"
            " AND array_position(document_ids, NULL) IS NULL"
            " AND cardinality(document_ids) >= 1"
            " AND cardinality(document_ids) <= 50)",
            name=op.f("ck_chat_sessions_document_ids_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspaces.id", "workspaces.owner_id"],
            name=op.f("fk_chat_sessions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
    )
    op.create_index(
        "ix_chat_sessions_user_id_updated_at",
        "chat_sessions",
        ["user_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_sessions_workspace_id_updated_at",
        "chat_sessions",
        ["workspace_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "insufficient_context",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("retrieval_ms", sa.Integer(), nullable=True),
        sa.Column("generation_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT insufficient_context OR jsonb_array_length(citations) = 0",
            name=op.f("ck_chat_messages_insufficient_context_no_citations"),
        ),
        sa.CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name=op.f("ck_chat_messages_completion_tokens_non_negative"),
        ),
        sa.CheckConstraint("content <> ''", name=op.f("ck_chat_messages_content_non_empty")),
        sa.CheckConstraint(
            "generation_ms IS NULL OR generation_ms >= 0",
            name=op.f("ck_chat_messages_generation_ms_non_negative"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(citations) = 'array'",
            name=op.f("ck_chat_messages_citations_is_array"),
        ),
        sa.CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
            name=op.f("ck_chat_messages_prompt_tokens_non_negative"),
        ),
        sa.CheckConstraint(
            "retrieval_ms IS NULL OR retrieval_ms >= 0",
            name=op.f("ck_chat_messages_retrieval_ms_non_negative"),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name=op.f("ck_chat_messages_role_valid")
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_chat_messages_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_messages_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint("session_id", "sequence", name="uq_chat_messages_session_id_sequence"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_workspace_id_updated_at", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id_updated_at", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_constraint("uq_workspaces_id_owner_id", "workspaces", type_="unique")
