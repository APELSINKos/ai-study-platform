import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

TOKEN_HASH_LENGTH: Final = 64
USER_AGENT_MAX_LENGTH: Final = 255


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(USER_AGENT_MAX_LENGTH), default=None)
