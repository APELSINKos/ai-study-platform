from collections.abc import Iterator
from typing import Final

import pytest
from openai import Timeout
from pydantic import SecretStr

from app.api.deps import collapse_ipv6, get_query_embedder
from app.core.config import Settings
from app.llm.factory import CONNECT_TIMEOUT_SECONDS, get_openai_client
from app.llm.mock_provider import HashingEmbeddingProvider
from app.llm.openai_provider import OpenAIEmbeddingProvider

_API_KEY: Final = "query-api-key-used-only-in-tests-000000"


@pytest.fixture
def _fresh_clients() -> Iterator[None]:
    get_openai_client.cache_clear()
    yield
    get_openai_client.cache_clear()


def test_ipv4_address_is_left_exact() -> None:
    assert collapse_ipv6("203.0.113.42") == "203.0.113.42"


def test_ipv6_address_is_collapsed_to_its_64_network() -> None:
    assert collapse_ipv6("2001:db8:1234:5678:aaaa:bbbb:cccc:dddd") == "2001:db8:1234:5678::"


def test_two_ipv6_addresses_in_the_same_64_network_collapse_to_the_same_value() -> None:
    first = collapse_ipv6("2001:db8:1234:5678::1")
    second = collapse_ipv6("2001:db8:1234:5678:ffff:ffff:ffff:ffff")

    assert first == second


def test_ipv6_addresses_in_different_64_networks_stay_distinct() -> None:
    assert collapse_ipv6("2001:db8:1234:5678::1") != collapse_ipv6("2001:db8:1234:5679::1")


def test_non_ip_strings_pass_through_unchanged() -> None:
    assert collapse_ipv6("unknown") == "unknown"
    assert collapse_ipv6("testclient") == "testclient"


def test_a_search_without_an_embeddings_key_gets_the_built_in_embedder(
    settings: Settings,
) -> None:
    assert isinstance(get_query_embedder(settings), HashingEmbeddingProvider)


@pytest.mark.usefixtures("_fresh_clients")
def test_a_search_gets_the_embeddings_model_with_the_search_limits() -> None:
    settings = Settings(
        environment="test",
        openai_api_key=SecretStr(_API_KEY),
        search_embedding_timeout_seconds=4.0,
    )

    provider = get_query_embedder(settings)

    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.model_name == settings.embedding_model
    assert provider.client.timeout == Timeout(4.0, connect=CONNECT_TIMEOUT_SECONDS)
    assert provider.client.max_retries == 0
