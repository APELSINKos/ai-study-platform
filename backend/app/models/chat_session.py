import uuid
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

CHAT_SESSION_TITLE_MAX_LENGTH: Final = 200
MAX_SCOPE_DOCUMENTS: Final = 50


class ChatSession(TimestampMixin, Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspaces.id", "workspaces.owner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "document_ids IS NULL OR ("
            "array_ndims(document_ids) = 1"
            " AND array_position(document_ids, NULL) IS NULL"
            " AND cardinality(document_ids) >= 1"
            f" AND cardinality(document_ids) <= {MAX_SCOPE_DOCUMENTS})",
            name="document_ids_valid",
        ),
        Index("ix_chat_sessions_user_id_updated_at", "user_id", "updated_at"),
        Index("ix_chat_sessions_workspace_id_updated_at", "workspace_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str | None] = mapped_column(String(CHAT_SESSION_TITLE_MAX_LENGTH), default=None)
    document_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        postgresql.ARRAY(sa.Uuid()), default=None
    )
    # Every write sets it from the application's clock; no onupdate for the same reason
    # as Workspace.updated_at.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
