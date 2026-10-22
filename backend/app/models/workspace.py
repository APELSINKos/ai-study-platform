import uuid
from datetime import date, datetime
from typing import Final

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

WORKSPACE_NAME_MAX_LENGTH: Final = 120
WORKSPACE_DESCRIPTION_MAX_LENGTH: Final = 1000


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (Index("ix_workspaces_owner_id_updated_at", "owner_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(WORKSPACE_NAME_MAX_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(
        String(WORKSPACE_DESCRIPTION_MAX_LENGTH), default=None
    )
    exam_date: Mapped[date | None] = mapped_column(Date, default=None)
    # Every write sets it from the application's clock. No onupdate: the unit of work leaves
    # out a time equal to the stored one, which would let the database's clock fill it in.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
