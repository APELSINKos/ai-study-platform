import json
from collections.abc import Iterator
from typing import Any, Final

import pytest
from openai import Omit, OpenAI, Timeout
from pydantic import SecretStr

from app.core.config import DEFAULT_OPENAI_BASE_URL, ResolvedProvider, Settings
from app.core.logging import configure_logging
from app.llm import factory
from app.llm.base import EmbeddingProvider, LLMProvider
from app.llm.factory import (
    CONNECT_TIMEOUT_SECONDS,
    ModelChoice,
    build_embedding_provider,
    build_llm_provider,
    get_openai_client,
    selected_models,
)
from app.llm.mock_provider import (
    MOCK_ANALYSIS_MODEL,
    MOCK_EMBEDDING_MODEL,
    HashingEmbeddingProvider,
    MockLLMProvider,
)
from app.llm.openai_provider import OpenAIEmbeddingProvider, OpenAILLMProvider
from app.llm.structured import ChatOptions

CHAT_API_KEY: Final = "chat-api-key-used-only-in-tests-000000"
EMBEDDING_API_KEY: Final = "embedding-api-key-used-only-in-tests-0"
CHAT_BASE_URL: Final = "https://openrouter.ai/api/v1"
EMBEDDING_BASE_URL: Final = "http://host.docker.internal:11434/v1"


@pytest.fixture(autouse=True)
def _isolated() -> Iterator[None]:
    # structlog keeps the logger it first used, so logging is set up before anything logs.
    configure_logging("INFO", "json")
    get_openai_client.cache_clear()
    yield
    get_openai_client.cache_clear()


def _settings(**values: Any) -> Settings:
    return Settings(environment="test", **values)


def _chat_provider(settings: Settings) -> OpenAILLMProvider:
    provider = build_llm_provider(settings)
    assert isinstance(provider, OpenAILLMProvider)
    return provider


def _embedding_provider(settings: Settings) -> OpenAIEmbeddingProvider:
    provider = build_embedding_provider(settings)
    assert isinstance(provider, OpenAIEmbeddingProvider)
    return provider


def _endpoint(client: OpenAI) -> tuple[str, str]:
    return client.api_key, str(client.base_url).rstrip("/")


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_the_test_settings_give_the_offline_providers(settings: Settings) -> None:
    assert isinstance(build_llm_provider(settings), MockLLMProvider)
    assert isinstance(build_embedding_provider(settings), HashingEmbeddingProvider)


def test_without_a_key_both_providers_stay_offline() -> None:
    settings = _settings()

    assert isinstance(build_llm_provider(settings), MockLLMProvider)
    assert isinstance(build_embedding_provider(settings), HashingEmbeddingProvider)


def test_forced_offline_providers_ignore_the_keys() -> None:
    settings = _settings(
        llm_provider="mock",
        embedding_provider="mock",
        openai_api_key=SecretStr(CHAT_API_KEY),
        embedding_api_key=SecretStr(EMBEDDING_API_KEY),
    )

    assert isinstance(build_llm_provider(settings), MockLLMProvider)
    assert isinstance(build_embedding_provider(settings), HashingEmbeddingProvider)


def test_building_the_offline_providers_creates_no_api_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_client(**_: object) -> OpenAI:
        raise AssertionError("an offline provider must not create an API client")

    monkeypatch.setattr(factory, "OpenAI", _no_client)
    settings = _settings()

    build_llm_provider(settings)
    build_embedding_provider(settings)


def test_an_openai_key_selects_the_chat_model_with_explicit_limits() -> None:
    settings = _settings(
        openai_api_key=SecretStr(CHAT_API_KEY), llm_structured_output="json_object"
    )

    provider = _chat_provider(settings)

    assert provider.model_name == settings.llm_model
    assert provider.options == ChatOptions(
        model=settings.llm_model,
        structured_output="json_object",
        max_output_tokens=settings.llm_max_output_tokens,
    )
    assert _endpoint(provider.client) == (CHAT_API_KEY, DEFAULT_OPENAI_BASE_URL)
    assert provider.client.timeout == Timeout(
        settings.llm_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS
    )
    assert provider.client.max_retries == settings.llm_max_retries


def test_the_chat_key_goes_to_the_llm_base_url() -> None:
    settings = _settings(openai_api_key=SecretStr(CHAT_API_KEY), llm_base_url=CHAT_BASE_URL)

    assert _endpoint(_chat_provider(settings).client) == (CHAT_API_KEY, CHAT_BASE_URL)


def test_an_exported_openai_base_url_is_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://elsewhere.example.com/v1")
    settings = _settings(openai_api_key=SecretStr(CHAT_API_KEY))

    assert _endpoint(_chat_provider(settings).client) == (CHAT_API_KEY, DEFAULT_OPENAI_BASE_URL)
    assert _endpoint(_embedding_provider(settings).client) == (
        CHAT_API_KEY,
        DEFAULT_OPENAI_BASE_URL,
    )


def test_other_exported_openai_variables_never_reach_an_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The SDK reads these by itself and would send them with every request, to any URL.
    monkeypatch.setenv("OPENAI_ORG_ID", "org-from-the-environment")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj_from_the_environment")
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS", "Authorization: Bearer another-key\nX-Gateway-Key: gateway-key"
    )
    settings = _settings(openai_api_key=SecretStr(CHAT_API_KEY), llm_base_url=CHAT_BASE_URL)

    for client in (_chat_provider(settings).client, _embedding_provider(settings).client):
        sent = {
            name.lower(): value
            for name, value in client.default_headers.items()
            if not isinstance(value, Omit)
        }
        assert not {"openai-organization", "openai-project", "x-gateway-key"} & sent.keys()
        assert "authorization" not in sent
        assert client.auth_headers == {"Authorization": f"Bearer {CHAT_API_KEY}"}


def test_embeddings_inherit_the_chat_key_together_with_its_url() -> None:
    settings = _settings(openai_api_key=SecretStr(CHAT_API_KEY), llm_base_url=CHAT_BASE_URL)

    provider = _embedding_provider(settings)

    assert provider.model_name == settings.embedding_model
    assert _endpoint(provider.client) == (CHAT_API_KEY, CHAT_BASE_URL)
    assert provider.client.timeout == Timeout(
        settings.embedding_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS
    )
    assert provider.client.max_retries == settings.llm_max_retries


def test_an_embedding_key_goes_to_openai_and_never_to_the_chat_url() -> None:
    settings = _settings(
        openai_api_key=SecretStr(CHAT_API_KEY),
        llm_base_url=CHAT_BASE_URL,
        embedding_api_key=SecretStr(EMBEDDING_API_KEY),
    )

    assert _endpoint(_embedding_provider(settings).client) == (
        EMBEDDING_API_KEY,
        DEFAULT_OPENAI_BASE_URL,
    )
    assert _endpoint(_chat_provider(settings).client) == (CHAT_API_KEY, CHAT_BASE_URL)


def test_an_embedding_key_and_url_are_used_together() -> None:
    settings = _settings(
        openai_api_key=SecretStr(CHAT_API_KEY),
        embedding_api_key=SecretStr(EMBEDDING_API_KEY),
        embedding_base_url=EMBEDDING_BASE_URL,
    )

    assert _endpoint(_embedding_provider(settings).client) == (
        EMBEDDING_API_KEY,
        EMBEDDING_BASE_URL,
    )


def test_an_embedding_key_alone_moves_only_the_embeddings_online() -> None:
    settings = _settings(
        embedding_api_key=SecretStr(EMBEDDING_API_KEY), embedding_base_url=EMBEDDING_BASE_URL
    )

    assert isinstance(build_llm_provider(settings), MockLLMProvider)
    assert _endpoint(_embedding_provider(settings).client) == (
        EMBEDDING_API_KEY,
        EMBEDDING_BASE_URL,
    )


def test_one_client_serves_every_document_on_the_same_endpoint() -> None:
    settings = _settings(openai_api_key=SecretStr(CHAT_API_KEY))

    assert _chat_provider(settings).client is _chat_provider(settings).client
    assert _embedding_provider(settings).client is _embedding_provider(settings).client
    # The same key and URL with other limits get a client of their own.
    assert _chat_provider(settings).client is not _embedding_provider(settings).client


def _provider_of(provider: LLMProvider | EmbeddingProvider) -> ResolvedProvider:
    live = isinstance(provider, OpenAILLMProvider | OpenAIEmbeddingProvider)
    return "openai" if live else "mock"


@pytest.mark.parametrize(
    "values",
    [
        {},
        {
            "llm_provider": "mock",
            "embedding_provider": "mock",
            "openai_api_key": SecretStr(CHAT_API_KEY),
        },
        {"openai_api_key": SecretStr(CHAT_API_KEY), "llm_base_url": CHAT_BASE_URL},
        {"openai_api_key": SecretStr(CHAT_API_KEY), "embedding_provider": "mock"},
        {
            "embedding_api_key": SecretStr(EMBEDDING_API_KEY),
            "embedding_base_url": EMBEDDING_BASE_URL,
        },
    ],
    ids=["no-keys", "forced-offline", "chat-key", "offline-embeddings", "embedding-key-only"],
)
def test_the_selected_models_are_the_ones_the_builders_build(values: dict[str, Any]) -> None:
    settings = _settings(**values)
    chat = build_llm_provider(settings)
    embeddings = build_embedding_provider(settings)

    selection = selected_models(settings)

    assert selection.chat == ModelChoice(_provider_of(chat), chat.model_name)
    assert selection.embedding == ModelChoice(_provider_of(embeddings), embeddings.model_name)


def _selection_lines(output: str) -> list[dict[str, Any]]:
    return [line for line in _json_lines(output) if line["event"] == "ai_providers_selected"]


def _selection(line: dict[str, Any]) -> dict[str, Any]:
    return {key: line[key] for key in line if key.startswith(("llm_", "embedding_"))}


# A process logs each selection once, so every logging test selects a model name of its own.
def test_the_selection_is_logged_once_with_modes_and_model_names_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    settings = _settings(
        openai_api_key=SecretStr(CHAT_API_KEY),
        llm_base_url=CHAT_BASE_URL,
        llm_model="chat-model-logged-once",
        embedding_provider="mock",
    )

    for _ in range(3):
        build_llm_provider(settings)
        build_embedding_provider(settings)

    output = capsys.readouterr().out
    [line] = _selection_lines(output)
    assert line["level"] == "info"
    assert _selection(line) == {
        "llm_provider": "openai",
        "llm_model": "chat-model-logged-once",
        "embedding_provider": "mock",
        "embedding_model": MOCK_EMBEDDING_MODEL,
    }
    for secret in (CHAT_API_KEY, CHAT_BASE_URL, "openrouter"):
        assert secret not in output


def test_the_log_names_the_offline_analyser_next_to_a_live_embeddings_model(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    settings = _settings(
        llm_model="chat-model-never-used",
        embedding_api_key=SecretStr(EMBEDDING_API_KEY),
        embedding_base_url=EMBEDDING_BASE_URL,
        embedding_model="embedding-model-logged-once",
    )

    build_embedding_provider(settings)

    output = capsys.readouterr().out
    [line] = _selection_lines(output)
    assert _selection(line) == {
        "llm_provider": "mock",
        "llm_model": MOCK_ANALYSIS_MODEL,
        "embedding_provider": "openai",
        "embedding_model": "embedding-model-logged-once",
    }
    for secret in (EMBEDDING_API_KEY, EMBEDDING_BASE_URL, "host.docker.internal"):
        assert secret not in output
