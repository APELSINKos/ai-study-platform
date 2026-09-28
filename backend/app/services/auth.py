import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    INVALID_TOKEN_MESSAGE,
    AccessToken,
    burn_password_check,
    create_access_token,
    hash_opaque_token,
    hash_password,
    new_opaque_token,
    password_needs_rehash,
    verify_password,
)
from app.models.refresh_token import (
    REVOKED_REUSE_DETECTED,
    REVOKED_ROTATED,
    REVOKED_SIGNED_OUT,
    USER_AGENT_MAX_LENGTH,
    RefreshToken,
)
from app.models.user import User
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository

logger = structlog.get_logger(__name__)

_EMAIL_TAKEN_MESSAGE: Final = "An account with this email already exists."
_INVALID_CREDENTIALS_MESSAGE: Final = "Incorrect email or password."
_INVALID_REFRESH_TOKEN_MESSAGE: Final = "Your session has ended. Sign in again."  # noqa: S105 -- user-facing text


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class IssuedSession:
    access_token: AccessToken
    refresh_token: str
    refresh_expires_at: datetime
    csrf_token: str


class AuthService:
    """Registration, authentication and refresh-token session lifecycle."""

    def __init__(
        self, session: Session, settings: Settings, clock: Callable[[], datetime] = utcnow
    ) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    def register(self, *, email: str, password: str, display_name: str) -> User:
        normalized_email = normalize_email(email)
        if self._users.get_by_email(normalized_email) is not None:
            raise ConflictError(_EMAIL_TAKEN_MESSAGE, code="email_taken")
        user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            display_name=display_name.strip(),
        )
        try:
            self._users.add(user)
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError(_EMAIL_TAKEN_MESSAGE, code="email_taken") from exc
        return user

    def authenticate(self, *, email: str, password: str) -> User:
        user = self._users.get_by_email(normalize_email(email))
        if user is None:
            burn_password_check(password)
            raise AuthenticationError(_INVALID_CREDENTIALS_MESSAGE, code="invalid_credentials")
        if not verify_password(password, user.password_hash) or not user.is_active:
            raise AuthenticationError(_INVALID_CREDENTIALS_MESSAGE, code="invalid_credentials")
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            self._session.commit()
        return user

    def start_session(self, user: User, *, user_agent: str | None) -> IssuedSession:
        issued = self._issue_session(
            user, family_id=uuid.uuid4(), user_agent=user_agent, now=self._clock()
        )
        self._session.commit()
        return issued

    def issue_access_token(self, user: User) -> AccessToken:
        """Issue a bearer access token with no refresh token or session state.

        Used by the OAuth2 password form (`/token`), which only needs a token for
        Swagger's "Authorize" dialog and has nowhere to deliver a refresh cookie.
        """
        return create_access_token(
            user.id,
            secret=self._settings.secret_key.get_secret_value(),
            ttl=timedelta(minutes=self._settings.access_token_ttl_minutes),
            now=self._clock(),
        )

    def rotate_session(
        self, refresh_token: str, *, user_agent: str | None
    ) -> tuple[User, IssuedSession]:
        now = self._clock()
        token = self._refresh_tokens.get_by_hash(hash_opaque_token(refresh_token))
        if token is None or token.expires_at <= now:
            raise AuthenticationError(_INVALID_REFRESH_TOKEN_MESSAGE, code="invalid_refresh_token")
        user = self._users.get(token.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError(_INVALID_REFRESH_TOKEN_MESSAGE, code="invalid_refresh_token")
        if token.revoked_at is None:
            self._refresh_tokens.revoke(token, now, REVOKED_ROTATED)
        else:
            self._reject_reused_token(token, token.revoked_at, user, now)
        issued = self._issue_session(
            user, family_id=token.family_id, user_agent=user_agent, now=now
        )
        self._session.commit()
        return user, issued

    def _reject_reused_token(
        self, token: RefreshToken, revoked_at: datetime, user: User, now: datetime
    ) -> None:
        """Raise unless a rotated token is replayed inside its own grace window."""
        grace = timedelta(seconds=self._settings.refresh_reuse_grace_seconds)
        within_grace = token.revocation_reason == REVOKED_ROTATED and now - revoked_at <= grace
        if within_grace and self._refresh_tokens.family_has_active_token(token.family_id, now):
            return
        if token.revocation_reason == REVOKED_ROTATED and not within_grace:
            self._refresh_tokens.revoke_family(token.family_id, now, REVOKED_REUSE_DETECTED)
            self._session.commit()
            logger.warning(
                "refresh_token_reuse_detected", user_id=str(user.id), family_id=str(token.family_id)
            )
        raise AuthenticationError(_INVALID_REFRESH_TOKEN_MESSAGE, code="invalid_refresh_token")

    def end_session(self, refresh_token: str | None) -> None:
        if refresh_token is None:
            return
        token = self._refresh_tokens.get_by_hash(hash_opaque_token(refresh_token))
        if token is None:
            return
        self._refresh_tokens.revoke_family(token.family_id, self._clock(), REVOKED_SIGNED_OUT)
        self._session.commit()

    def get_active_user(self, user_id: uuid.UUID) -> User:
        user = self._users.get(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError(INVALID_TOKEN_MESSAGE, code="invalid_token")
        return user

    def _issue_session(
        self, user: User, *, family_id: uuid.UUID, user_agent: str | None, now: datetime
    ) -> IssuedSession:
        raw_token = new_opaque_token()
        refresh_expires_at = now + timedelta(days=self._settings.refresh_token_ttl_days)
        self._refresh_tokens.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id,
                token_hash=hash_opaque_token(raw_token),
                expires_at=refresh_expires_at,
                user_agent=_truncate_user_agent(user_agent),
            )
        )
        access_token = create_access_token(
            user.id,
            secret=self._settings.secret_key.get_secret_value(),
            ttl=timedelta(minutes=self._settings.access_token_ttl_minutes),
            now=now,
        )
        return IssuedSession(
            access_token=access_token,
            refresh_token=raw_token,
            refresh_expires_at=refresh_expires_at,
            csrf_token=new_opaque_token(),
        )


def _truncate_user_agent(user_agent: str | None) -> str | None:
    if user_agent is None:
        return None
    return user_agent[:USER_AGENT_MAX_LENGTH]
