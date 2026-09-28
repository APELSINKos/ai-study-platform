import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Direct database access for users. Holds no business rules and never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        return self._session.execute(statement).scalar_one_or_none()

    def add(self, user: User) -> User:
        self._session.add(user)
        self._session.flush()
        return user
