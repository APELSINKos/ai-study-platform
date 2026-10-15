"""Choosing the analysis and embedding providers that the settings ask for."""

from dataclasses import dataclass
from functools import cache, lru_cache
from typing import Final

import structlog
from openai import OpenAI, Timeout

from app.core.config import DEFAULT_OPENAI_BASE_URL, ProviderEndpoint, ResolvedProvider, Settings
from app.llm.base import EmbeddingProvider, LLMProvider
from app.llm.mock_provider import (
    MOCK_ANALYSIS_MODEL,
    MOCK_EMBEDDING_MODEL,
    HashingEmbeddingProvider,
    MockLLMProvider,
)
from app.llm.openai_provider import OpenAIEmbeddingProvider, OpenAILLMProvider
from app.llm.structured import ChatOptions

logger = structlog.get_logger(__name__)

CONNECT_TIMEOUT_SECONDS: Final = 5.0


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """A provider and the name of its model, as stored with each document it processes."""

    provider: ResolvedProvider
    model: str


@dataclass(frozen=True, slots=True)
class ModelSelection:
    """The model that analyses documents and the one that embeds their chunks."""

    chat: ModelChoice
    embedding: ModelChoice


def selected_models(settings: Settings) -> ModelSelection:
    """The models that the builders below pick for these settings, found without a client."""
    chat = ModelChoice("mock", MOCK_ANALYSIS_MODEL)
    if _chat_endpoint(settings) is not None:
        chat = ModelChoice("openai", settings.llm_model)
    embedding = ModelChoice("mock", MOCK_EMBEDDING_MODEL)
    if _embedding_endpoint(settings) is not None:
        embedding = ModelChoice("openai", settings.embedding_model)
    return ModelSelection(chat=chat, embedding=embedding)


def build_llm_provider(settings: Settings) -> LLMProvider:
    """The chat model the settings select, or the offline heuristic analysis."""
    _log_selection(settings)
    endpoint = _chat_endpoint(settings)
    if endpoint is None:
        return MockLLMProvider()
    options = ChatOptions(
        model=settings.llm_model,
        structured_output=settings.llm_structured_output,
        max_output_tokens=settings.llm_max_output_tokens,
    )
    client = _client(endpoint, settings.llm_timeout_seconds, settings.llm_max_retries)
    return OpenAILLMProvider(client=client, options=options)


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """The embeddings model the settings select, or the offline hashing embeddings."""
    _log_selection(settings)
    endpoint = _embedding_endpoint(settings)
    if endpoint is None:
        return HashingEmbeddingProvider()
    client = _client(endpoint, settings.embedding_timeout_seconds, settings.llm_max_retries)
    return OpenAIEmbeddingProvider(client=client, model=settings.embedding_model)


@lru_cache
def get_openai_client(
    api_key: str, base_url: str, timeout_seconds: float, max_retries: int
) -> OpenAI:
    """One client per endpoint and limits, so its connections are reused between documents.

    Keyed by plain values because Settings are not hashable. A client is made on first use,
    never at import, so each forked worker process makes its own. The key and URL are always
    given, so the SDK never falls back to OPENAI_API_KEY or OPENAI_BASE_URL itself.
    """
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
        max_retries=max_retries,
    )


def _chat_endpoint(settings: Settings) -> ProviderEndpoint | None:
    """Where analysis requests go, or None for the offline analysis."""
    if settings.resolved_llm_provider == "mock" or settings.openai_api_key is None:
        return None
    # The chat key is only ever sent to LLM_BASE_URL, or to OpenAI when that is blank.
    return ProviderEndpoint(
        api_key=settings.openai_api_key,
        base_url=settings.llm_base_url or DEFAULT_OPENAI_BASE_URL,
    )


def _embedding_endpoint(settings: Settings) -> ProviderEndpoint | None:
    """Where embedding requests go, or None for the offline embeddings."""
    if settings.resolved_embedding_provider == "mock":
        return None
    return settings.embedding_endpoint


def _client(endpoint: ProviderEndpoint, timeout_seconds: float, max_retries: int) -> OpenAI:
    return get_openai_client(
        endpoint.api_key.get_secret_value(), endpoint.base_url, timeout_seconds, max_retries
    )


def _log_selection(settings: Settings) -> None:
    _log_once(selected_models(settings))


# Cached so that a process logs its providers once, not for every document. Keys and URLs
# are never logged.
@cache
def _log_once(selection: ModelSelection) -> None:
    logger.info(
        "ai_providers_selected",
        llm_provider=selection.chat.provider,
        llm_model=selection.chat.model,
        embedding_provider=selection.embedding.provider,
        embedding_model=selection.embedding.model,
    )
