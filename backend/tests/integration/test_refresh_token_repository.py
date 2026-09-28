import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.refresh_token import REVOKED_ROTATED, REVOKED_SIGNED_OUT, RefreshToken
from app.models.user import User
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository

pytestmark = pytest.mark.integration

_TOKEN_TTL = timedelta(days=14)


def _make_user(session: Session, email: str) -> User:
    user = User(email=email, password_hash="hash", display_name="Person")
    return UserRepository(session).add(user)


def _make_token(user_id: uuid.UUID, *, family_id: uuid.UUID | None = None) -> RefreshToken:
    now = datetime.now(UTC)
    return RefreshToken(
        user_id=user_id,
        family_id=family_id or uuid.uuid4(),
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        expires_at=now + _TOKEN_TTL,
    )


def test_add_assigns_an_id_and_persists_the_token(db_session: Session) -> None:
    user = _make_user(db_session, "token-owner@example.com")
    repository = RefreshTokenRepository(db_session)

    token = repository.add(_make_token(user.id))

    assert isinstance(token.id, uuid.UUID)
    assert repository.get_by_hash(token.token_hash) is token


def test_get_by_hash_returns_none_when_missing(db_session: Session) -> None:
    repository = RefreshTokenRepository(db_session)

    assert repository.get_by_hash("missing") is None


def test_deleting_a_user_cascades_to_its_tokens(db_session: Session) -> None:
    user = _make_user(db_session, "cascade@example.com")
    repository = RefreshTokenRepository(db_session)
    token = repository.add(_make_token(user.id))

    db_session.delete(user)
    db_session.flush()
    db_session.expunge_all()

    assert repository.get_by_hash(token.token_hash) is None


def test_revoke_sets_revoked_at_and_reason_only_once(db_session: Session) -> None:
    user = _make_user(db_session, "revoke@example.com")
    repository = RefreshTokenRepository(db_session)
    token = repository.add(_make_token(user.id))
    first = datetime.now(UTC)
    later = first + timedelta(minutes=1)

    repository.revoke(token, first, REVOKED_ROTATED)
    repository.revoke(token, later, REVOKED_SIGNED_OUT)

    assert token.revoked_at == first
    assert token.revocation_reason == REVOKED_ROTATED


def test_revoke_family_revokes_only_that_familys_active_tokens(db_session: Session) -> None:
    user = _make_user(db_session, "family@example.com")
    repository = RefreshTokenRepository(db_session)
    family_a = uuid.uuid4()
    family_b = uuid.uuid4()
    active_in_family = repository.add(_make_token(user.id, family_id=family_a))
    already_revoked = repository.add(_make_token(user.id, family_id=family_a))
    pre_existing_revocation = datetime.now(UTC)
    repository.revoke(already_revoked, pre_existing_revocation, REVOKED_ROTATED)
    other_family_token = repository.add(_make_token(user.id, family_id=family_b))

    now = datetime.now(UTC) + timedelta(minutes=1)
    count = repository.revoke_family(family_a, now, REVOKED_SIGNED_OUT)

    assert count == 1
    assert active_in_family.revoked_at == now
    assert active_in_family.revocation_reason == REVOKED_SIGNED_OUT
    assert already_revoked.revoked_at == pre_existing_revocation
    assert already_revoked.revocation_reason == REVOKED_ROTATED
    assert other_family_token.revoked_at is None


def test_revoke_all_for_user_counts_correctly(db_session: Session) -> None:
    user = _make_user(db_session, "all-tokens@example.com")
    other_user = _make_user(db_session, "other-user@example.com")
    repository = RefreshTokenRepository(db_session)
    token_one = repository.add(_make_token(user.id))
    token_two = repository.add(_make_token(user.id))
    other_users_token = repository.add(_make_token(other_user.id))

    now = datetime.now(UTC)
    count = repository.revoke_all_for_user(user.id, now, REVOKED_SIGNED_OUT)

    assert count == 2
    assert token_one.revoked_at == now
    assert token_one.revocation_reason == REVOKED_SIGNED_OUT
    assert token_two.revoked_at == now
    assert other_users_token.revoked_at is None


def test_family_has_active_token_is_true_when_an_active_token_exists(db_session: Session) -> None:
    user = _make_user(db_session, "active-family@example.com")
    repository = RefreshTokenRepository(db_session)
    family_id = uuid.uuid4()
    repository.add(_make_token(user.id, family_id=family_id))

    assert repository.family_has_active_token(family_id, datetime.now(UTC)) is True


def test_family_has_active_token_is_false_when_every_token_is_revoked_or_expired(
    db_session: Session,
) -> None:
    user = _make_user(db_session, "dead-family@example.com")
    repository = RefreshTokenRepository(db_session)
    family_id = uuid.uuid4()
    now = datetime.now(UTC)
    revoked = repository.add(_make_token(user.id, family_id=family_id))
    repository.revoke(revoked, now, REVOKED_SIGNED_OUT)
    repository.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            expires_at=now - timedelta(minutes=1),
        )
    )

    assert repository.family_has_active_token(family_id, now) is False


def test_family_has_active_token_is_false_for_an_unknown_family(db_session: Session) -> None:
    repository = RefreshTokenRepository(db_session)

    assert repository.family_has_active_token(uuid.uuid4(), datetime.now(UTC)) is False
