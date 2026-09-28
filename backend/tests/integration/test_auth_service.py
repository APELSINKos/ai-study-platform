import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.logging import configure_logging
from app.core.security import decode_access_token, hash_opaque_token, verify_password
from app.models.refresh_token import USER_AGENT_MAX_LENGTH
from app.models.user import User
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository
from app.services.auth import AuthService, normalize_email

pytestmark = pytest.mark.integration

_PASSWORD: Final = "correct horse battery staple"  # noqa: S105 -- test fixture, not a secret
# Real wall-clock time: create_access_token's iat/exp are validated by PyJWT against
# the real clock on decode, so the fake clock has to start close to it.
_START: Final = utcnow()


class _FakeClock:
    """A callable clock whose time only moves when the test tells it to."""

    def __init__(self, start: datetime = _START) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_normalize_email_strips_whitespace_and_lowercases() -> None:
    assert normalize_email("  Person@Example.COM  ") == "person@example.com"


def test_register_normalizes_the_email_and_strips_the_display_name(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings)

    user = service.register(
        email="  Person@Example.COM  ", password=_PASSWORD, display_name="  Person  "
    )

    assert user.email == "person@example.com"
    assert user.display_name == "Person"
    assert user.password_hash != _PASSWORD
    assert verify_password(_PASSWORD, user.password_hash) is True


def test_register_persists_the_user(db_session: Session, integration_settings: Settings) -> None:
    service = AuthService(db_session, integration_settings)

    user = service.register(
        email="persisted@example.com", password=_PASSWORD, display_name="Person"
    )

    assert UserRepository(db_session).get(user.id) is not None


def test_register_rejects_an_email_already_in_use_case_insensitively(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings)
    service.register(email="taken@example.com", password=_PASSWORD, display_name="First")

    with pytest.raises(ConflictError) as exc_info:
        service.register(email="Taken@Example.com", password=_PASSWORD, display_name="Second")

    assert exc_info.value.code == "email_taken"


def test_register_converts_a_concurrent_duplicate_insert_into_a_conflict_error(
    db_session: Session, integration_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    UserRepository(db_session).add(
        User(email="race@example.com", password_hash="hash", display_name="Existing")  # noqa: S106
    )
    db_session.commit()
    # Simulate two requests racing past the availability check for the same e-mail.
    monkeypatch.setattr(UserRepository, "get_by_email", lambda _self, _email: None)
    service = AuthService(db_session, integration_settings)

    with pytest.raises(ConflictError) as exc_info:
        service.register(email="race@example.com", password=_PASSWORD, display_name="New")

    assert exc_info.value.code == "email_taken"


def test_authenticate_returns_the_user_for_correct_credentials(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings)
    registered = service.register(
        email="login@example.com", password=_PASSWORD, display_name="Person"
    )

    user = service.authenticate(email="  Login@Example.com  ", password=_PASSWORD)

    assert user.id == registered.id


def test_authenticate_fails_identically_for_unknown_email_wrong_password_and_inactive_user(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings)
    service.register(email="wrong-pw@example.com", password=_PASSWORD, display_name="Person")
    inactive = service.register(
        email="inactive@example.com", password=_PASSWORD, display_name="Person"
    )
    inactive.is_active = False
    db_session.commit()

    with pytest.raises(AuthenticationError) as unknown_email:
        service.authenticate(email="missing@example.com", password=_PASSWORD)
    with pytest.raises(AuthenticationError) as wrong_password:
        service.authenticate(email="wrong-pw@example.com", password="not the password")  # noqa: S106
    with pytest.raises(AuthenticationError) as inactive_user:
        service.authenticate(email="inactive@example.com", password=_PASSWORD)

    errors = [unknown_email.value, wrong_password.value, inactive_user.value]
    assert {error.code for error in errors} == {"invalid_credentials"}
    assert {error.message for error in errors} == {"Incorrect email or password."}


def test_authenticate_rehashes_the_password_when_the_hasher_flags_it(
    db_session: Session, integration_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = AuthService(db_session, integration_settings)
    registered = service.register(
        email="rehash@example.com", password=_PASSWORD, display_name="Person"
    )
    original_hash = registered.password_hash
    monkeypatch.setattr("app.services.auth.password_needs_rehash", lambda _password_hash: True)

    user = service.authenticate(email="rehash@example.com", password=_PASSWORD)

    assert user.password_hash != original_hash
    db_session.expire(user)
    reloaded_hash = user.password_hash
    assert reloaded_hash != original_hash
    assert verify_password(_PASSWORD, reloaded_hash) is True


def test_start_session_issues_tokens_and_stores_only_the_refresh_token_hash(
    db_session: Session, integration_settings: Settings
) -> None:
    clock = _FakeClock()
    service = AuthService(db_session, integration_settings, clock)
    user = service.register(email="session@example.com", password=_PASSWORD, display_name="Person")

    issued = service.start_session(user, user_agent="pytest-agent")

    assert (
        decode_access_token(
            issued.access_token.value, secret=integration_settings.secret_key.get_secret_value()
        )
        == user.id
    )
    ttl = timedelta(minutes=integration_settings.access_token_ttl_minutes)
    assert issued.access_token.expires_at == _START + ttl
    refresh_ttl = timedelta(days=integration_settings.refresh_token_ttl_days)
    assert issued.refresh_expires_at == _START + refresh_ttl
    assert issued.refresh_token
    assert issued.csrf_token != issued.refresh_token

    repo = RefreshTokenRepository(db_session)
    stored = repo.get_by_hash(hash_opaque_token(issued.refresh_token))
    assert stored is not None
    assert stored.user_id == user.id
    assert stored.user_agent == "pytest-agent"
    # The raw token itself must never be stored or searchable as-is.
    assert repo.get_by_hash(issued.refresh_token) is None


def test_start_session_truncates_a_long_user_agent(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings, _FakeClock())
    user = service.register(email="ua@example.com", password=_PASSWORD, display_name="Person")
    long_agent = "A" * (USER_AGENT_MAX_LENGTH + 50)

    issued = service.start_session(user, user_agent=long_agent)

    stored = RefreshTokenRepository(db_session).get_by_hash(hash_opaque_token(issued.refresh_token))
    assert stored is not None
    assert stored.user_agent == long_agent[:USER_AGENT_MAX_LENGTH]


def test_start_session_uses_a_new_family_and_csrf_token_each_time(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings, _FakeClock())
    user = service.register(email="families@example.com", password=_PASSWORD, display_name="Person")

    first = service.start_session(user, user_agent=None)
    second = service.start_session(user, user_agent=None)

    assert first.csrf_token != second.csrf_token
    repo = RefreshTokenRepository(db_session)
    first_token = repo.get_by_hash(hash_opaque_token(first.refresh_token))
    second_token = repo.get_by_hash(hash_opaque_token(second.refresh_token))
    assert first_token is not None
    assert second_token is not None
    assert first_token.family_id != second_token.family_id


def test_rotate_session_returns_a_new_refresh_token_and_revokes_the_old_one(
    db_session: Session, integration_settings: Settings
) -> None:
    clock = _FakeClock()
    service = AuthService(db_session, integration_settings, clock)
    user = service.register(email="rotate@example.com", password=_PASSWORD, display_name="Person")
    issued = service.start_session(user, user_agent="agent-a")

    rotated_user, rotated = service.rotate_session(issued.refresh_token, user_agent="agent-b")

    assert rotated_user.id == user.id
    assert rotated.refresh_token != issued.refresh_token

    repo = RefreshTokenRepository(db_session)
    original = repo.get_by_hash(hash_opaque_token(issued.refresh_token))
    fresh = repo.get_by_hash(hash_opaque_token(rotated.refresh_token))
    assert original is not None
    assert original.revoked_at == clock()
    assert fresh is not None
    assert fresh.revoked_at is None
    assert fresh.family_id == original.family_id
    assert fresh.user_agent == "agent-b"


def test_rotate_session_fails_for_an_unknown_token(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings, _FakeClock())

    with pytest.raises(AuthenticationError) as exc_info:
        service.rotate_session("not-a-real-token", user_agent=None)

    assert exc_info.value.code == "invalid_refresh_token"


def test_rotate_session_fails_for_an_expired_token(
    db_session: Session, integration_settings: Settings
) -> None:
    clock = _FakeClock()
    service = AuthService(db_session, integration_settings, clock)
    user = service.register(email="expired@example.com", password=_PASSWORD, display_name="Person")
    issued = service.start_session(user, user_agent=None)
    clock.advance(timedelta(days=integration_settings.refresh_token_ttl_days, seconds=1))

    with pytest.raises(AuthenticationError) as exc_info:
        service.rotate_session(issued.refresh_token, user_agent=None)

    assert exc_info.value.code == "invalid_refresh_token"


def test_rotate_session_fails_for_an_inactive_user(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings, _FakeClock())
    user = service.register(
        email="deactivated@example.com", password=_PASSWORD, display_name="Person"
    )
    issued = service.start_session(user, user_agent=None)
    user.is_active = False
    db_session.commit()

    with pytest.raises(AuthenticationError) as exc_info:
        service.rotate_session(issued.refresh_token, user_agent=None)

    assert exc_info.value.code == "invalid_refresh_token"


def test_rotate_session_reuse_within_the_grace_window_issues_a_fresh_session(
    db_session: Session, integration_settings: Settings
) -> None:
    clock = _FakeClock()
    service = AuthService(db_session, integration_settings, clock)
    user = service.register(
        email="concurrent@example.com", password=_PASSWORD, display_name="Person"
    )
    original = service.start_session(user, user_agent=None)

    _, first_tab = service.rotate_session(original.refresh_token, user_agent="tab-a")
    clock.advance(timedelta(seconds=integration_settings.refresh_reuse_grace_seconds - 1))
    second_user, second_tab = service.rotate_session(original.refresh_token, user_agent="tab-b")

    assert second_user.id == user.id
    assert second_tab.refresh_token != first_tab.refresh_token

    repo = RefreshTokenRepository(db_session)
    first_tab_token = repo.get_by_hash(hash_opaque_token(first_tab.refresh_token))
    second_tab_token = repo.get_by_hash(hash_opaque_token(second_tab.refresh_token))
    assert first_tab_token is not None
    assert second_tab_token is not None
    assert first_tab_token.revoked_at is None
    assert second_tab_token.revoked_at is None
    assert first_tab_token.family_id == second_tab_token.family_id


def test_rotate_session_reuse_outside_the_grace_window_revokes_the_family_and_logs_a_warning(
    db_session: Session, integration_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO", "json")
    clock = _FakeClock()
    service = AuthService(db_session, integration_settings, clock)
    user = service.register(email="theft@example.com", password=_PASSWORD, display_name="Person")
    original = service.start_session(user, user_agent=None)
    _, newest = service.rotate_session(original.refresh_token, user_agent=None)
    clock.advance(timedelta(seconds=integration_settings.refresh_reuse_grace_seconds + 1))

    with pytest.raises(AuthenticationError) as exc_info:
        service.rotate_session(original.refresh_token, user_agent=None)

    assert exc_info.value.code == "invalid_refresh_token"
    [warning] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "refresh_token_reuse_detected"
    ]
    assert warning["level"] == "warning"
    assert warning["user_id"] == str(user.id)

    repo = RefreshTokenRepository(db_session)
    original_token = repo.get_by_hash(hash_opaque_token(original.refresh_token))
    newest_token = repo.get_by_hash(hash_opaque_token(newest.refresh_token))
    assert original_token is not None
    assert newest_token is not None
    assert original_token.revoked_at is not None
    assert newest_token.revoked_at is not None
    assert warning["family_id"] == str(newest_token.family_id)

    # A later rotation with the newest token of the now-revoked family fails too.
    clock.advance(timedelta(seconds=integration_settings.refresh_reuse_grace_seconds + 1))
    with pytest.raises(AuthenticationError) as later_exc_info:
        service.rotate_session(newest.refresh_token, user_agent=None)
    assert later_exc_info.value.code == "invalid_refresh_token"


def test_end_session_revokes_the_whole_family(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings, _FakeClock())
    user = service.register(email="logout@example.com", password=_PASSWORD, display_name="Person")
    original = service.start_session(user, user_agent=None)
    _, rotated = service.rotate_session(original.refresh_token, user_agent=None)

    service.end_session(rotated.refresh_token)

    repo = RefreshTokenRepository(db_session)
    original_token = repo.get_by_hash(hash_opaque_token(original.refresh_token))
    rotated_token = repo.get_by_hash(hash_opaque_token(rotated.refresh_token))
    assert original_token is not None
    assert rotated_token is not None
    assert original_token.revoked_at is not None
    assert rotated_token.revoked_at is not None


def test_end_session_is_a_no_op_for_none(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings, _FakeClock())

    service.end_session(None)


def test_end_session_is_a_no_op_for_an_unknown_token(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings, _FakeClock())

    service.end_session("unknown-token")


def test_get_active_user_returns_the_user(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings)
    user = service.register(email="active@example.com", password=_PASSWORD, display_name="Person")

    assert service.get_active_user(user.id).id == user.id


def test_get_active_user_fails_for_an_unknown_id(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings)

    with pytest.raises(AuthenticationError) as exc_info:
        service.get_active_user(uuid.uuid4())

    assert exc_info.value.code == "invalid_token"


def test_get_active_user_fails_for_an_inactive_user(
    db_session: Session, integration_settings: Settings
) -> None:
    service = AuthService(db_session, integration_settings)
    user = service.register(
        email="deactivated2@example.com", password=_PASSWORD, display_name="Person"
    )
    user.is_active = False
    db_session.commit()

    with pytest.raises(AuthenticationError) as exc_info:
        service.get_active_user(user.id)

    assert exc_info.value.code == "invalid_token"
