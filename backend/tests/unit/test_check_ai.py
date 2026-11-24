import re
from collections.abc import Sequence
from typing import Any, Final

import httpx2
import pytest
from openai import OpenAI
from pydantic import SecretStr

from app.check_ai import main
from app.core.config import Settings
from app.core.logging import configure_logging
from app.llm.base import (
    AnalysisRequest,
    AnalysisResult,
    ChatRequest,
    ChatResult,
    ProviderError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.llm.mock_provider import HashingEmbeddingProvider, MockLLMProvider
from app.llm.openai_provider import OpenAIEmbeddingProvider, OpenAILLMProvider
from app.llm.probe import PROBE_SENTENCE, UNSENDABLE_KEY_MESSAGE
from app.llm.structured import ChatOptions

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
# Neither key nor any part of an address: an endpoint is only named, never located.
_LEAKS: Final = (
    _CHAT_KEY,
    _EMBEDDING_KEY,
    "://",
    "api.openai.com",
    "openrouter",
    "host.docker.internal",
    "11434",
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

    def answer_question(
        self, request: ChatRequest, *, timeout_budget_seconds: float | None = None
    ) -> ChatResult:
        if self._error is not None:
            raise self._error
        return MockLLMProvider().answer_question(
            request, timeout_budget_seconds=timeout_budget_seconds
        )


def _offline() -> Settings:
    return Settings(environment="test", llm_provider="mock", embedding_provider="mock")


def _live(**values: Any) -> Settings:
    """Settings with a chat key, which the embeddings also use unless values say otherwise."""
    return Settings(environment="test", **{"openai_api_key": SecretStr(_CHAT_KEY), **values})


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def _assert_nothing_leaked(out: str, err: str) -> None:
    for leak in _LEAKS:
        assert leak not in out
        assert leak not in err


def _refuse_connection(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("Connection refused", request=request)


def _client_with_an_unsendable_key() -> OpenAI:
    """A client whose key was pasted with a no-break space; a request would be refused."""
    return OpenAI(
        api_key=f"{_CHAT_KEY}\N{NO-BREAK SPACE}",
        base_url="http://llm.test/v1",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(_refuse_connection)),
    )


def test_the_built_in_models_are_named_and_the_embedding_model_answers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([], settings=_offline()) == 0

    lines = _lines(capsys)
    assert "Chat model: mock-heuristic-v1 (provider mock, built in)" in lines
    assert "Embedding model: mock-hashing-v1 (provider mock, built in)" in lines
    assert any(_EMBEDDING_LATENCY.fullmatch(line) for line in lines)
    assert lines[-1] == _NOT_EXERCISED


def test_no_info_log_line_interrupts_the_report(capsys: pytest.CaptureFixture[str]) -> None:
    # Info lines would show in the output, as they do in a process that sets up no logging.
    configure_logging("INFO", "console")
    # A process logs each choice of models once, so this test chooses a chat model of its own.
    settings = _live(llm_model="chat-model-of-a-quiet-check", embedding_provider="mock")

    assert main([], settings=settings) == 0

    lines = _lines(capsys)
    assert lines[:2] == [
        "Chat model: chat-model-of-a-quiet-check (provider openai, OpenAI)",
        "Embedding model: mock-hashing-v1 (provider mock, built in)",
    ]
    assert _EMBEDDING_LATENCY.fullmatch(lines[2])
    assert lines[3:] == [_NOT_EXERCISED]


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


def test_a_failing_embedding_model_exits_with_1_and_its_error_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chat = _ChatModel()

    assert main([], settings=_offline(), embedder=_Embedder(_UNAVAILABLE), llm=chat) == 1

    assert chat.requests == []
    assert _lines(capsys)[-2:] == [
        "The embedding model failed: ai_unavailable (The AI provider could not be reached.)",
        _NOT_EXERCISED,
    ]


def test_with_chat_the_chat_model_is_probed_even_when_the_embedding_model_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chat = _ChatModel()

    assert main(["--chat"], settings=_offline(), embedder=_Embedder(_UNAVAILABLE), llm=chat) == 1

    assert len(chat.requests) == 1
    lines = _lines(capsys)
    assert lines[-2] == (
        "The embedding model failed: ai_unavailable (The AI provider could not be reached.)"
    )
    assert _CHAT_LATENCY.fullmatch(lines[-1])


def test_a_failing_chat_model_exits_with_1_and_its_error_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chat = _ChatModel(_REJECTED)

    assert main(["--chat"], settings=_offline(), embedder=_Embedder(), llm=chat) == 1

    assert _lines(capsys)[-1] == (
        "The chat model failed: ai_rejected"
        " (The AI provider rejected the request: HTTP 404 (model_not_found).)"
    )


def test_an_embedding_key_that_cannot_be_sent_is_named_as_the_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with _client_with_an_unsendable_key() as client:
        embedder = OpenAIEmbeddingProvider(client=client, model="text-embedding-3-small")

        assert main([], settings=_offline(), embedder=embedder) == 1

    captured = capsys.readouterr()
    assert captured.out.splitlines()[-2:] == [
        f"The embedding model failed: {UNSENDABLE_KEY_MESSAGE}",
        _NOT_EXERCISED,
    ]
    assert _CHAT_KEY not in captured.out
    assert _CHAT_KEY not in captured.err


def test_a_chat_key_that_cannot_be_sent_is_named_as_the_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    options = ChatOptions(
        model="gpt-5.4-mini", structured_output="json_schema", max_output_tokens=700
    )
    with _client_with_an_unsendable_key() as client:
        llm = OpenAILLMProvider(client=client, options=options)

        assert main(["--chat"], settings=_offline(), embedder=_Embedder(), llm=llm) == 1

    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1] == f"The chat model failed: {UNSENDABLE_KEY_MESSAGE}"
    assert _CHAT_KEY not in captured.out
    assert _CHAT_KEY not in captured.err


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
    _assert_nothing_leaked(captured.out, captured.err)


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
    (
        {"llm_base_url": "https://openai-proxy.example.com/v1"},
        "gpt-5.4-mini (provider openai, custom endpoint)",
        "text-embedding-3-small (provider openai, custom endpoint)",
    ),
    (
        {"llm_base_url": "https://api.openai.com.example.com/v1"},
        "gpt-5.4-mini (provider openai, custom endpoint)",
        "text-embedding-3-small (provider openai, custom endpoint)",
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
        "openai-lookalike-host",
        "openai-prefixed-host",
    ],
)
def test_each_endpoint_is_named_openai_or_custom_endpoint(
    capsys: pytest.CaptureFixture[str], values: dict[str, Any], chat: str, embedding: str
) -> None:
    assert main([], settings=_live(**values), embedder=_Embedder()) == 0

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[:2] == [f"Chat model: {chat}", f"Embedding model: {embedding}"]
    assert _EMBEDDING_LATENCY.fullmatch(lines[2])
    assert lines[3:] == [_NOT_EXERCISED]
    _assert_nothing_leaked(captured.out, captured.err)
