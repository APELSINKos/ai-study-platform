import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.users import UserRepository

pytestmark = pytest.mark.integration


def _make_user(email: str = "person@example.com") -> User:
    return User(email=email, password_hash="hash", display_name="Person")


def test_add_assigns_an_id_and_persists_the_user(db_session: Session) -> None:
    repository = UserRepository(db_session)

    user = repository.add(_make_user())

    assert isinstance(user.id, uuid.UUID)
    assert repository.get(user.id) is user


def test_get_returns_none_for_an_unknown_id(db_session: Session) -> None:
    repository = UserRepository(db_session)

    assert repository.get(uuid.uuid4()) is None


def test_get_by_email_finds_the_user_with_the_email_normalized_to_lowercase(
    db_session: Session,
) -> None:
    repository = UserRepository(db_session)
    repository.add(_make_user("Mixed@Example.com"))

    found = repository.get_by_email("mixed@example.com")

    assert found is not None
    assert found.email == "mixed@example.com"


def test_get_by_email_returns_none_when_no_user_matches(db_session: Session) -> None:
    repository = UserRepository(db_session)

    assert repository.get_by_email("missing@example.com") is None


def test_duplicate_email_raises_integrity_error(db_session: Session) -> None:
    repository = UserRepository(db_session)
    repository.add(_make_user("dup@example.com"))

    with pytest.raises(IntegrityError):
        repository.add(_make_user("dup@example.com"))
