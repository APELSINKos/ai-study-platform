import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


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
