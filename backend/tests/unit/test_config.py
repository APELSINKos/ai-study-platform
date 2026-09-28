import pytest
from pydantic import ValidationError

from app.core.config import DEV_SECRET_KEY, Settings, get_settings


def test_cors_origins_are_read_from_a_comma_separated_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://study.example.com ,")

    assert Settings().cors_origins == ["http://localhost:3000", "https://study.example.com"]


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_returns_one_shared_instance() -> None:
    assert get_settings() is get_settings()


def test_empty_metrics_token_means_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_TOKEN", "")

    assert Settings().metrics_token is None


def test_production_rejects_the_development_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(ValidationError):
        Settings()


def test_production_accepts_a_sufficiently_long_secret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)

    assert Settings().environment == "production"


def test_empty_secret_key_falls_back_to_the_development_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "")

    assert Settings().secret_key.get_secret_value() == DEV_SECRET_KEY


def test_empty_cookie_secure_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COOKIE_SECURE", "")

    assert Settings().cookie_secure is None


def test_secure_cookies_follows_an_explicit_override() -> None:
    assert Settings(cookie_secure=True).secure_cookies is True
    assert Settings(cookie_secure=False).secure_cookies is False


def test_secure_cookies_defaults_to_is_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)

    settings = Settings()

    assert settings.cookie_secure is None
    assert settings.secure_cookies is settings.is_production is True
