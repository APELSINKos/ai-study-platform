import uuid
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User

_NUL: Final = "\x00"


class UserRepository:
    """Direct database access for users. Holds no business rules and never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        if _NUL in email:
            # PostgreSQL text cannot hold NUL, so no stored email has it, and the driver
            # refuses to send it in a query.
            return None
        statement = select(User).where(User.email == email)
        return self._session.execute(statement).scalar_one_or_none()

    def add(self, user: User) -> User:
        self._session.add(user)
        self._session.flush()
        return user

    def lock(self, user_id: uuid.UUID) -> None:
        """Lock the user's row until the transaction ends.

        FOR NO KEY UPDATE: a second such lock waits, while rows that only reference the user,
        such as a new workspace or refresh token, need KEY SHARE and go in at once.
        """
        statement = select(User.id).where(User.id == user_id).with_for_update(key_share=True)
        self._session.execute(statement)
