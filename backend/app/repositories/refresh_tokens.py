import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    """Direct database access for refresh tokens. Holds no business rules and never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, token: RefreshToken) -> RefreshToken:
        self._session.add(token)
        self._session.flush()
        return token

    def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        statement = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return self._session.execute(statement).scalar_one_or_none()

    def revoke(self, token: RefreshToken, now: datetime, reason: str) -> None:
        if token.revoked_at is None:
            token.revoked_at = now
            token.revocation_reason = reason

    def revoke_family(self, family_id: uuid.UUID, now: datetime, reason: str) -> int:
        statement = (
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revocation_reason=reason)
            .returning(RefreshToken.id)
        )
        revoked_ids = self._session.execute(statement).scalars().all()
        self._expire_revoked_tokens(revoked_ids)
        return len(revoked_ids)

    def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime, reason: str) -> int:
        statement = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revocation_reason=reason)
            .returning(RefreshToken.id)
        )
        revoked_ids = self._session.execute(statement).scalars().all()
        self._expire_revoked_tokens(revoked_ids)
        return len(revoked_ids)

    def family_has_active_token(self, family_id: uuid.UUID, now: datetime) -> bool:
        statement = (
            select(RefreshToken.id)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def _expire_revoked_tokens(self, revoked_ids: Sequence[uuid.UUID]) -> None:
        # A bulk UPDATE bypasses the ORM, so identity-mapped instances the caller
        # already holds (or fetched earlier in this session) would otherwise keep
        # their stale, pre-revocation attribute values until something reloads them.
        ids = set(revoked_ids)
        if not ids:
            return
        for obj in list(self._session.identity_map.values()):
            if isinstance(obj, RefreshToken) and obj.id in ids:
                self._session.expire(obj)
