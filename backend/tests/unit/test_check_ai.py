import re
from collections.abc import Sequence
from typing import Any, Final

import pytest
from pydantic import SecretStr

from app.check_ai import main
from app.core.config import Settings
from app.llm.base import (
    AnalysisRequest,
    AnalysisResult,
    ProviderError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.llm.mock_provider import HashingEmbeddingProvider, MockLLMProvider
from app.llm.probe import PROBE_SENTENCE

# Invented, and as long as a real key.
_CHAT_KEY: Final = "chat-key-for-check-ai-tests-".ljust(40, "0")
_EMBEDDING_KEY: Final = "embedding-key-for-check-ai-tests-".ljust(40, "0")
_CHAT_URL: Final = "https://openrouter.ai/api/v1"
_EMBEDDING_URL: Final = "http://host.docker.internal:11434/v1"
_EMBEDDING_LATENCY: Final = re.compile(r"The embedding model answered in \d+(\.\d+)? ms\.")
_CHAT_LATENCY: Final = re.compile(r"The chat model answered in \d+(\.\d+)? ms\.")
_NOT_EXERCISED: Final = (
    "The chat model was not exercised; run with --chat to send it one small analysis request."
)
_UNAVAILABLE: Final = ProviderUnavailableError("The AI provider could not be reached.")
_REJECTED: Final = ProviderRequestError(
    "The AI provider rejected the request: HTTP 404 (model_not_found).", code="ai_rejected"
)


class _Embedder:
    """The built-in embeddings, or the given error; records each request."""

    def __init__(self, error: ProviderError | None = None) -> None:
        self.requests: list[list[str]] = []
        self._error = error

    @property
    def model_name(self) -> str:
        return "text-embedding-3-small"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.requests.append(list(texts))
        if self._error is not None:
            raise self._error
        return HashingEmbeddingProvider().embed(texts)


class _ChatModel:
    """The built-in analysis, or the given error; records each request."""

    def __init__(self, error: ProviderError | None = None) -> None:
        self.requests: list[AnalysisRequest] = []
        self._error = error

    @property
    def model_name(self) -> str:
        return "gpt-5.4-mini"

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return MockLLMProvider().analyze_document(request)


def _offline() -> Settings:
    return Settings(environment="test", llm_provider="mock", embedding_provider="mock")


def _live(**values: Any) -> Settings:
    """Settings with a chat key, which the embeddings also use unless values say otherwise."""
    return Settings(environment="test", **{"openai_api_key": SecretStr(_CHAT_KEY), **values})


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_the_built_in_models_are_named_and_the_embedding_model_answers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([], settings=_offline()) == 0

    lines = _lines(capsys)
    assert "Chat model: mock-heuristic-v1 (provider mock, built in)" in lines
    assert "Embedding model: mock-hashing-v1 (provider mock, built in)" in lines
    assert any(_EMBEDDING_LATENCY.fullmatch(line) for line in lines)
    assert lines[-1] == _NOT_EXERCISED


def test_with_chat_the_chat_model_gets_one_small_analysis_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    embedder = _Embedder()
    chat = _ChatModel()

    assert main(["--chat"], settings=_offline(), embedder=embedder, llm=chat) == 0

    assert embedder.requests == [[PROBE_SENTENCE]]
    assert chat.requests == [
        AnalysisRequest(filename="probe.txt", outline="", sample=PROBE_SENTENCE)
    ]
    lines = _lines(capsys)
    assert _CHAT_LATENCY.fullmatch(lines[-1])
    assert _NOT_EXERCISED not in lines


def test_with_chat_the_built_in_analysis_answers_too(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--chat"], settings=_offline()) == 0

    assert _CHAT_LATENCY.fullmatch(_lines(capsys)[-1])


def test_without_chat_the_chat_model_gets_no_request(capsys: pytest.CaptureFixture[str]) -> None:
    chat = _ChatModel()

    assert main([], settings=_offline(), embedder=_Embedder(), llm=chat) == 0

    assert chat.requests == []
    assert _lines(capsys)[-1] == _NOT_EXERCISED


@pytest.mark.parametrize("args", [[], ["--chat"]], ids=["embeddings-only", "with-chat"])
def test_a_failing_embedding_model_exits_with_1_and_its_error_code(
    capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    chat = _ChatModel()

    assert main(args, settings=_offline(), embedder=_Embedder(_UNAVAILABLE), llm=chat) == 1

    assert chat.requests == []
    assert _lines(capsys)[-1] == (
        "The embedding model failed: ai_unavailable (The AI provider could not be reached.)"
    )


def test_a_failing_chat_model_exits_with_1_and_its_error_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chat = _ChatModel(_REJECTED)

    assert main(["--chat"], settings=_offline(), embedder=_Embedder(), llm=chat) == 1

    assert _lines(capsys)[-1] == (
        "The chat model failed: ai_rejected"
        " (The AI provider rejected the request: HTTP 404 (model_not_found).)"
    )


@pytest.mark.parametrize(
    ("embedding_error", "chat_error"),
    [(None, None), (_UNAVAILABLE, None), (None, _REJECTED)],
    ids=["both-answer", "embeddings-fail", "chat-fails"],
)
def test_neither_a_key_nor_an_address_is_ever_printed(
    capsys: pytest.CaptureFixture[str],
    embedding_error: ProviderError | None,
    chat_error: ProviderError | None,
) -> None:
    settings = _live(
        llm_base_url=_CHAT_URL,
        embedding_api_key=SecretStr(_EMBEDDING_KEY),
        embedding_base_url=_EMBEDDING_URL,
    )

    main(
        ["--chat"],
        settings=settings,
        embedder=_Embedder(embedding_error),
        llm=_ChatModel(chat_error),
    )

    captured = capsys.readouterr()
    for secret in (_CHAT_KEY, _EMBEDDING_KEY, _CHAT_URL, _EMBEDDING_URL):
        assert secret not in captured.out
        assert secret not in captured.err


# Built in each test, after the provider variables of the environment are cleared.
_ENDPOINTS: Final[list[tuple[dict[str, Any], str, str]]] = [
    (
        {},
        "gpt-5.4-mini (provider openai, OpenAI)",
        "text-embedding-3-small (provider openai, OpenAI)",
    ),
    (
        {"llm_base_url": "https://api.openai.com/v1/"},
        "gpt-5.4-mini (provider openai, OpenAI)",
        "text-embedding-3-small (provider openai, OpenAI)",
    ),
    # Without a key of their own, the embeddings go where the chat key goes.
    (
        {"llm_base_url": _CHAT_URL},
        "gpt-5.4-mini (provider openai, custom endpoint)",
        "text-embedding-3-small (provider openai, custom endpoint)",
    ),
    (
        {
            "embedding_api_key": SecretStr(_EMBEDDING_KEY),
            "embedding_base_url": _EMBEDDING_URL,
            "embedding_model": "nomic-embed-text",
        },
        "gpt-5.4-mini (provider openai, OpenAI)",
        "nomic-embed-text (provider openai, custom endpoint)",
    ),
    (
        {"openai_api_key": None, "embedding_api_key": SecretStr(_EMBEDDING_KEY)},
        "mock-heuristic-v1 (provider mock, built in)",
        "text-embedding-3-small (provider openai, OpenAI)",
    ),
    (
        {"embedding_provider": "mock"},
        "gpt-5.4-mini (provider openai, OpenAI)",
        "mock-hashing-v1 (provider mock, built in)",
    ),
]


@pytest.mark.parametrize(
    ("values", "chat", "embedding"),
    _ENDPOINTS,
    ids=[
        "openai",
        "openai-with-a-trailing-slash",
        "custom-chat-endpoint",
        "custom-embedding-endpoint",
        "embedding-key-only",
        "built-in-embeddings",
    ],
)
def test_each_endpoint_is_named_openai_or_custom_endpoint(
    capsys: pytest.CaptureFixture[str], values: dict[str, Any], chat: str, embedding: str
) -> None:
    assert main([], settings=_live(**values), embedder=_Embedder()) == 0

    lines = _lines(capsys)
    assert f"Chat model: {chat}" in lines
    assert f"Embedding model: {embedding}" in lines
