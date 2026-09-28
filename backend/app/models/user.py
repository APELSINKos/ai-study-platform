import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import Boolean, DateTime, String, func, true
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base, TimestampMixin

EMAIL_MAX_LENGTH: Final = 320
DISPLAY_NAME_MAX_LENGTH: Final = 80
PASSWORD_HASH_MAX_LENGTH: Final = 255


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH), nullable=False)
    display_name: Mapped[str] = mapped_column(String(DISPLAY_NAME_MAX_LENGTH), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @validates("email")
    def _normalize_email(self, _key: str, value: str) -> str:
        return value.lower()
