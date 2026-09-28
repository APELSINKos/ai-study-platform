import json
import re
import uuid
from datetime import timedelta
from typing import Any

import jwt
import pytest

from app.core.clock import utcnow
from app.core.exceptions import AuthenticationError
from app.core.logging import configure_logging
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    JWT_ALGORITHM,
    burn_password_check,
    create_access_token,
    decode_access_token,
    hash_opaque_token,
    hash_password,
    new_opaque_token,
    verify_password,
)

# 32 bytes, matching MIN_SECRET_KEY_LENGTH: pyjwt warns (and filterwarnings turns it into
# an error) about HMAC keys shorter than that.
SECRET = "unit-test-jwt-signing-secret-key"  # noqa: S105 -- dummy secret used only in these tests


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_hash_password_returns_a_hash_that_verifies() -> None:
    password = "correct horse battery staple"  # noqa: S105 -- test fixture, not a secret

    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash) is True


def test_verify_password_rejects_the_wrong_password() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("wrong password", password_hash) is False


def test_verify_password_returns_false_and_logs_when_the_hash_is_corrupted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")

    result = verify_password("any password", "not-a-valid-argon2-hash")

    assert result is False
    [line] = _json_lines(capsys.readouterr().out)
    assert line["event"] == "password_hash_unreadable"
    assert line["level"] == "error"


def test_burn_password_check_does_not_raise() -> None:
    burn_password_check("whatever password")


def test_access_token_round_trips_the_user_id() -> None:
    user_id = uuid.uuid4()
    now = utcnow()

    token = create_access_token(user_id, secret=SECRET, ttl=timedelta(minutes=15), now=now)

    assert token.expires_at == now + timedelta(minutes=15)
    assert decode_access_token(token.value, secret=SECRET) == user_id


def test_decode_access_token_rejects_an_expired_token() -> None:
    token = create_access_token(
        uuid.uuid4(), secret=SECRET, ttl=timedelta(seconds=-1), now=utcnow()
    )

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token.value, secret=SECRET)

    assert exc_info.value.code == "token_expired"


def test_decode_access_token_rejects_a_token_signed_with_another_secret() -> None:
    token = create_access_token(
        uuid.uuid4(), secret=SECRET, ttl=timedelta(minutes=15), now=utcnow()
    )
    other_secret = "a-completely-different-signing-secret"  # noqa: S105 -- test fixture

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token.value, secret=other_secret)

    assert exc_info.value.code == "invalid_token"


def test_decode_access_token_rejects_a_tampered_payload() -> None:
    token = create_access_token(
        uuid.uuid4(), secret=SECRET, ttl=timedelta(minutes=15), now=utcnow()
    )
    header, _payload, signature = token.value.split(".")
    other_user_payload = jwt.utils.base64url_encode(
        json.dumps({"sub": str(uuid.uuid4())}).encode()
    ).decode()

    tampered = f"{header}.{other_user_payload}.{signature}"

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(tampered, secret=SECRET)

    assert exc_info.value.code == "invalid_token"


def test_decode_access_token_rejects_a_token_that_is_not_an_access_token() -> None:
    now = utcnow()
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    token = jwt.encode(payload, SECRET, algorithm=JWT_ALGORITHM)

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token, secret=SECRET)

    assert exc_info.value.code == "invalid_token"


def test_decode_access_token_rejects_a_token_missing_the_subject_claim() -> None:
    now = utcnow()
    payload = {
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    token = jwt.encode(payload, SECRET, algorithm=JWT_ALGORITHM)

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token, secret=SECRET)

    assert exc_info.value.code == "invalid_token"


def test_hash_opaque_token_is_deterministic_and_hex_encoded() -> None:
    token = "some-opaque-token-value"  # noqa: S105 -- test fixture, not a secret

    digest = hash_opaque_token(token)

    assert hash_opaque_token(token) == digest
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_hash_opaque_token_differs_for_different_inputs() -> None:
    assert hash_opaque_token("token-a") != hash_opaque_token("token-b")


def test_new_opaque_token_values_differ_and_are_url_safe() -> None:
    first = new_opaque_token()
    second = new_opaque_token()

    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)
