import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import jwt
import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.exceptions import AuthenticationError

JWT_ALGORITHM: Final = "HS256"
ACCESS_TOKEN_TYPE: Final = "access"  # noqa: S105 -- a token kind label, not a credential
OPAQUE_TOKEN_BYTES: Final = 32
_REQUIRED_CLAIMS: Final = ["sub", "exp", "iat", "type"]
_INVALID_TOKEN_MESSAGE: Final = "The access token is invalid."  # noqa: S105 -- user-facing text

logger = structlog.get_logger(__name__)
_hasher = PasswordHasher()
# Verifying against a real hash when the account does not exist keeps both paths equally slow.
_DUMMY_PASSWORD_HASH: Final = _hasher.hash(secrets.token_urlsafe(OPAQUE_TOKEN_BYTES))


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at: datetime


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False
    except InvalidHashError:
        logger.error("password_hash_unreadable")
        return False


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_PASSWORD_HASH)


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(
    user_id: uuid.UUID, *, secret: str, ttl: timedelta, now: datetime
) -> AccessToken:
    expires_at = now + ttl
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    return AccessToken(jwt.encode(payload, secret, algorithm=JWT_ALGORITHM), expires_at)


def decode_access_token(token: str, *, secret: str) -> uuid.UUID:
    try:
        payload = jwt.decode(
            token, secret, algorithms=[JWT_ALGORITHM], options={"require": _REQUIRED_CLAIMS}
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("The session has expired.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError(_INVALID_TOKEN_MESSAGE, code="invalid_token") from exc
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise AuthenticationError(_INVALID_TOKEN_MESSAGE, code="invalid_token")
    try:
        return uuid.UUID(str(payload["sub"]))
    except ValueError as exc:
        raise AuthenticationError(_INVALID_TOKEN_MESSAGE, code="invalid_token") from exc


def new_opaque_token() -> str:
    return secrets.token_urlsafe(OPAQUE_TOKEN_BYTES)


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
