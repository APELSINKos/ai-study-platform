from pathlib import Path
from typing import Final

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import DEV_SECRET_KEY, Settings, get_settings
from app.models.document import MODEL_NAME_MAX_LENGTH

# compose.yaml passes these through as ${VAR:-}, so an unset variable arrives blank.
PASS_THROUGH_VARIABLES: Final = (
    "LLM_PROVIDER",
    "OPENAI_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_API_KEY",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_MODEL",
)
OPENAI_BASE_URL: Final = "https://api.openai.com/v1"
OPENROUTER_BASE_URL: Final = "https://openrouter.ai/api/v1"
LOCAL_BASE_URL: Final = "http://host.docker.internal:11434/v1"
CHAT_API_KEY: Final = "chat-api-key-used-only-in-tests-000000"
EMBEDDING_API_KEY: Final = "embedding-api-key-used-only-in-tests-0"
PRODUCTION_SECRET_KEY: Final = "x" * 40


@pytest.fixture(autouse=True)
def _without_storage_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    # The dev containers set it; the provider variables are cleared for every test.
    monkeypatch.delenv("STORAGE_DIR", raising=False)


def test_cors_origins_are_read_from_a_comma_separated_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://study.example.com ,")

    assert Settings().cors_origins == ["http://localhost:3000", "https://study.example.com"]


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings()


def test_a_settings_error_never_repeats_the_values_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A key pasted into the wrong variable is one field's error...
    monkeypatch.setenv("LLM_PROVIDER", CHAT_API_KEY)
    with pytest.raises(ValidationError) as field_error:
        Settings()
    # ...and a key set next to a URL it may not go to fails the settings as a whole.
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)
    monkeypatch.setenv("EMBEDDING_BASE_URL", LOCAL_BASE_URL)
    with pytest.raises(ValidationError) as settings_error:
        Settings()

    for error in (field_error.value, settings_error.value):
        assert "input_value" not in str(error)
        assert CHAT_API_KEY[:8] not in str(error)
        assert CHAT_API_KEY[-8:] not in str(error)


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


def test_document_settings_default_to_the_documented_limits() -> None:
    settings = Settings()

    assert settings.storage_dir == Path("/data/uploads")
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert settings.max_pdf_pages == 500
    assert settings.max_document_chars == 2_000_000
    assert settings.chunk_size_chars == 1200
    assert settings.chunk_overlap_chars == 200
    assert settings.embedding_batch_size == 64
    assert settings.analysis_max_input_chars == 12_000
    assert settings.uploads_per_hour == 60
    assert settings.document_retries_per_hour == 30
    assert settings.max_active_documents_per_user == 10
    assert settings.max_storage_bytes_per_user == 1024**3


def test_provider_settings_default_to_the_offline_models() -> None:
    settings = Settings()

    assert settings.llm_provider == settings.embedding_provider == "auto"
    assert settings.openai_api_key is None
    assert settings.embedding_api_key is None
    assert settings.llm_base_url is None
    assert settings.embedding_base_url is None
    assert settings.llm_model == "gpt-5.4-mini"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.llm_structured_output == "json_schema"
    assert settings.llm_timeout_seconds == 60
    assert settings.embedding_timeout_seconds == 30
    assert settings.llm_max_retries == 1
    assert settings.llm_max_output_tokens == 1000
    assert settings.resolved_llm_provider == settings.resolved_embedding_provider == "mock"
    assert settings.embedding_endpoint is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_pass_through_variables_fall_back_to_the_defaults(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    for name in PASS_THROUGH_VARIABLES:
        monkeypatch.setenv(name, blank)

    settings = Settings()

    for name in PASS_THROUGH_VARIABLES:
        field = name.lower()
        assert getattr(settings, field) == Settings.model_fields[field].default


def test_a_blank_environment_is_still_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "")

    with pytest.raises(ValidationError, match="environment"):
        Settings()


@pytest.mark.parametrize("overlap", [1200, 1500])
def test_chunk_overlap_must_be_smaller_than_the_chunk_size(overlap: int) -> None:
    with pytest.raises(ValidationError, match="CHUNK_OVERLAP_CHARS"):
        Settings(chunk_size_chars=1200, chunk_overlap_chars=overlap)


@pytest.mark.parametrize("batch_size", [0, 2049])
def test_embedding_batch_size_fits_one_api_request(batch_size: int) -> None:
    with pytest.raises(ValidationError, match="embedding_batch_size"):
        Settings(embedding_batch_size=batch_size)


@pytest.mark.parametrize("variable", ["LLM_MODEL", "EMBEDDING_MODEL"])
def test_a_model_name_fits_the_column_that_records_it_with_each_document(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    longest = "m" * MODEL_NAME_MAX_LENGTH
    monkeypatch.setenv(variable, longest)

    assert getattr(Settings(), variable.lower()) == longest

    monkeypatch.setenv(variable, longest + "m")
    with pytest.raises(ValidationError, match=variable.lower()):
        Settings()


def test_an_openai_key_switches_both_auto_providers_to_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)

    settings = Settings()

    assert settings.resolved_llm_provider == "openai"
    assert settings.resolved_embedding_provider == "openai"


def test_forced_mock_providers_ignore_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")

    settings = Settings()

    assert settings.resolved_llm_provider == "mock"
    assert settings.resolved_embedding_provider == "mock"


@pytest.mark.parametrize("environment", ["development", "test", "production"])
@pytest.mark.parametrize("variable", ["LLM_PROVIDER", "EMBEDDING_PROVIDER"])
def test_forcing_openai_without_a_key_is_rejected_in_every_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str, variable: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("SECRET_KEY", PRODUCTION_SECRET_KEY)
    monkeypatch.setenv(variable, "openai")

    with pytest.raises(ValidationError, match=variable):
        Settings()


def test_a_whitespace_only_key_counts_as_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "   ")

    assert Settings().resolved_llm_provider == "mock"
    assert Settings(openai_api_key=SecretStr("   ")).openai_api_key is None

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        Settings()


def test_embeddings_reuse_the_chat_key_and_url_when_no_embedding_endpoint_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)
    monkeypatch.setenv("LLM_BASE_URL", OPENROUTER_BASE_URL)

    endpoint = Settings().embedding_endpoint

    assert endpoint is not None
    assert endpoint.api_key.get_secret_value() == CHAT_API_KEY
    assert endpoint.base_url == OPENROUTER_BASE_URL


def test_a_reused_chat_key_without_a_url_goes_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)

    endpoint = Settings().embedding_endpoint

    assert endpoint is not None
    assert endpoint.base_url == OPENAI_BASE_URL


def test_an_embedding_key_goes_to_openai_and_never_to_the_chat_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Chat through OpenRouter, embeddings from OpenAI.
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)
    monkeypatch.setenv("LLM_BASE_URL", OPENROUTER_BASE_URL)
    monkeypatch.setenv("EMBEDDING_API_KEY", EMBEDDING_API_KEY)

    endpoint = Settings().embedding_endpoint

    assert endpoint is not None
    assert endpoint.api_key.get_secret_value() == EMBEDDING_API_KEY
    assert endpoint.base_url == OPENAI_BASE_URL


def test_an_embedding_url_without_its_own_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reusing the chat key here would send it to a server it was not issued for.
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)
    monkeypatch.setenv("EMBEDDING_BASE_URL", LOCAL_BASE_URL)

    with pytest.raises(ValidationError, match="EMBEDDING_BASE_URL"):
        Settings()


def test_an_embedding_key_and_url_are_used_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)
    monkeypatch.setenv("EMBEDDING_API_KEY", EMBEDDING_API_KEY)
    monkeypatch.setenv("EMBEDDING_BASE_URL", LOCAL_BASE_URL)

    endpoint = Settings().embedding_endpoint

    assert endpoint is not None
    assert endpoint.api_key.get_secret_value() == EMBEDDING_API_KEY
    assert endpoint.base_url == LOCAL_BASE_URL
    assert EMBEDDING_API_KEY not in repr(endpoint)


def test_an_embedding_key_alone_switches_only_the_embeddings_to_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_API_KEY", EMBEDDING_API_KEY)

    settings = Settings()

    assert settings.resolved_llm_provider == "mock"
    assert settings.resolved_embedding_provider == "openai"


def test_forcing_openai_chat_with_only_an_embedding_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The embedding key never goes to the chat endpoint, so chat has no key of its own.
    monkeypatch.setenv("EMBEDDING_API_KEY", EMBEDDING_API_KEY)
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    with pytest.raises(ValidationError, match="LLM_PROVIDER=openai needs OPENAI_API_KEY"):
        Settings()


def test_forced_openai_embeddings_accept_the_reused_chat_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")

    assert Settings().resolved_embedding_provider == "openai"


@pytest.mark.parametrize(
    "fixture_name",
    ["settings", pytest.param("integration_settings", marks=pytest.mark.integration)],
)
def test_the_settings_fixtures_stay_offline_when_a_key_is_exported(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", CHAT_API_KEY)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")

    settings: Settings = request.getfixturevalue(fixture_name)

    assert settings.resolved_llm_provider == "mock"
    assert settings.resolved_embedding_provider == "mock"
    assert settings.storage_dir == tmp_path
