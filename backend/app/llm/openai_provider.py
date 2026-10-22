"""Analysis and embeddings through an OpenAI-compatible API: OpenAI, OpenRouter, Ollama and others.

Every failure becomes a ProviderError with a document error code. Its message is written here
from the HTTP status and the vendor's error code only: the API's own error text can quote the
key, so it is neither copied nor chained.
"""

import math
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final

import openai
from openai import OpenAI
from openai.types import CreateEmbeddingResponse, Embedding

from app.llm.base import (
    EMBEDDING_DIMENSIONS,
    AnalysisRequest,
    AnalysisResult,
    ProviderError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.llm.prompts import build_analysis_messages
from app.llm.schemas import DocumentAnalysis
from app.llm.structured import ChatOptions, complete_structured

# A 429 with one of these codes means a spent balance or budget, which waiting does not restore.
BILLING_ERROR_CODES: Final = frozenset(
    {
        "insufficient_quota",
        "credit_balance_exhausted",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    }
)
# Statuses below 500 that a later attempt may get past.
_TRANSIENT_STATUSES: Final = frozenset(
    {HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.CONFLICT, HTTPStatus.TOO_MANY_REQUESTS}
)
# Statuses from 500 up that no later attempt gets past: the server does not support the
# request at all, as a compatible server may answer for embeddings or a response format.
_PERMANENT_SERVER_STATUSES: Final = frozenset({HTTPStatus.NOT_IMPLEMENTED})
_VENDOR_CODE_MAX_CHARS: Final = 64
_MILLISECONDS_PER_SECOND: Final = 1000.0
_UNREACHABLE_MESSAGE: Final = "The AI provider could not be reached."
_TIMED_OUT_MESSAGE: Final = "The AI provider did not answer in time."
_UNREADABLE_MESSAGE: Final = "The AI provider sent a response that could not be read as JSON."
_BLANK_TEXT_MESSAGE: Final = "Texts to embed must not be blank."
_WRONG_VECTORS_MESSAGE: Final = "The embedding model did not return one vector per text."
_INVALID_VECTOR_MESSAGE: Final = (
    "The embedding model returned a vector that is not a non-zero list of finite numbers."
)


@dataclass(frozen=True, slots=True)
class OpenAILLMProvider:
    """Analyses documents with a chat model held to the DocumentAnalysis schema."""

    client: OpenAI
    options: ChatOptions

    @property
    def model_name(self) -> str:
        return self.options.model

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult:
        messages = build_analysis_messages(request)
        with _provider_errors():
            output = complete_structured(self.client, self.options, messages, DocumentAnalysis)
        # The configured name rather than the snapshot the endpoint reports, so that a retry
        # recognises the analysis it saved.
        return AnalysisResult(
            analysis=output.value,
            model=self.model_name,
            prompt_tokens=output.prompt_tokens,
            completion_tokens=output.completion_tokens,
        )


@dataclass(frozen=True, slots=True)
class OpenAIEmbeddingProvider:
    """Embeds texts with an embeddings model in one request per call.

    The caller keeps each call within the API's limit of inputs per request.
    """

    client: OpenAI
    model: str

    @property
    def model_name(self) -> str:
        return self.model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        # The API refuses an empty string, and compatible servers differ on blank ones.
        if any(not text.strip() for text in texts):
            raise ValueError(_BLANK_TEXT_MESSAGE)
        with _provider_errors():
            response = self.client.embeddings.create(
                model=self.model,
                input=list(texts),
                dimensions=EMBEDDING_DIMENSIONS,
                encoding_format="float",
            )
        return _unit_vectors(response, len(texts), self.model)


def classify_openai_error(error: openai.OpenAIError) -> ProviderError:
    """The provider error, transient or permanent and with its code, for an SDK error."""
    if isinstance(error, openai.APITimeoutError):
        return ProviderUnavailableError(_TIMED_OUT_MESSAGE)
    if isinstance(error, openai.APIConnectionError):
        return ProviderUnavailableError(_UNREACHABLE_MESSAGE)
    if not isinstance(error, openai.APIStatusError):
        return ProviderRequestError(
            f"The call to the AI provider failed: {type(error).__name__}.", code="ai_rejected"
        )
    status = error.status_code
    answer = f"HTTP {status}{_vendor_code(error)}"
    if status == HTTPStatus.PAYMENT_REQUIRED or (
        status == HTTPStatus.TOO_MANY_REQUESTS and _is_billing_limit(error)
    ):
        return ProviderRequestError(
            f"The AI provider's quota or credit is used up: {answer}.", code="ai_quota_exceeded"
        )
    if status in _TRANSIENT_STATUSES or (
        status >= HTTPStatus.INTERNAL_SERVER_ERROR and status not in _PERMANENT_SERVER_STATUSES
    ):
        return ProviderUnavailableError(
            f"The AI provider is busy or failing: {answer}.",
            retry_after_seconds=_retry_after_seconds(error.response.headers),
        )
    return ProviderRequestError(
        f"The AI provider rejected the request: {answer}.", code="ai_rejected"
    )


@contextmanager
def _provider_errors() -> Iterator[None]:
    """Raise a failed API call as a provider error, without chaining the SDK error."""
    try:
        yield
    except openai.OpenAIError as error:
        raise classify_openai_error(error) from None
    except UnicodeEncodeError:
        # A key or header the client cannot send: a setting to fix, not an answer to blame.
        raise
    except (ValueError, RecursionError, OverflowError):
        # The SDK lets these through for a body that claims to be JSON but cannot be read:
        # malformed, not UTF-8, with an integer longer than Python reads (a plain
        # ValueError), nested too deeply or with a number too large for a float.
        raise ProviderRequestError(_UNREADABLE_MESSAGE, code="ai_invalid_output") from None


def _vendor_code(error: openai.APIStatusError) -> str:
    """The vendor's error code, such as model_not_found, when it is a plain identifier."""
    code = error.code
    if code is not None and code.isidentifier() and len(code) <= _VENDOR_CODE_MAX_CHARS:
        return f" ({code})"
    return ""


def _is_billing_limit(error: openai.APIStatusError) -> bool:
    # Some vendors give the reason as the error type rather than its code.
    return any(
        isinstance(reason, str) and reason in BILLING_ERROR_CODES
        for reason in (error.code, error.type)
    )


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """The wait the response asks for, from retry-after-ms or a retry-after in seconds."""
    for name, units_per_second in (
        ("retry-after-ms", _MILLISECONDS_PER_SECOND),
        ("retry-after", 1.0),
    ):
        value = headers.get(name)
        if value is None:
            continue
        try:
            seconds = float(value) / units_per_second
        except ValueError:
            continue
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    return None


def _unit_vectors(response: CreateEmbeddingResponse, count: int, model: str) -> list[list[float]]:
    """The response's vectors in input order, each checked and scaled to unit length."""
    # The SDK does not validate a response: a body that is not JSON reaches here as a plain
    # string, and a part of another shape as the server sent it.
    data = response.data if isinstance(response, CreateEmbeddingResponse) else None
    items = data if isinstance(data, list) else []
    # An item of another shape is left out, and then the indices no longer cover every text.
    by_index = {
        item.index: item.embedding
        for item in items
        if isinstance(item, Embedding) and isinstance(item.index, int)
    }
    if len(items) != count or by_index.keys() != set(range(count)):
        raise ProviderRequestError(_WRONG_VECTORS_MESSAGE, code="ai_invalid_output")
    return [_unit_vector(by_index[index], model) for index in range(count)]


def _unit_vector(vector: list[float], model: str) -> list[float]:
    if not isinstance(vector, list):
        raise ProviderRequestError(_INVALID_VECTOR_MESSAGE, code="ai_invalid_output")
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ProviderRequestError(
            f"The embedding model {model} returned {len(vector)} dimensions; "
            f"the database stores {EMBEDDING_DIMENSIONS}.",
            code="embedding_dimension_mismatch",
        )
    if not all(isinstance(value, int | float) for value in vector):
        raise ProviderRequestError(_INVALID_VECTOR_MESSAGE, code="ai_invalid_output")
    # A NaN or an infinity makes the norm NaN or infinite, and so do finite values whose norm
    # is beyond the float range. hypot scales internally, so tiny values do not vanish.
    norm = math.hypot(*vector)
    if not 0.0 < norm < math.inf:
        raise ProviderRequestError(_INVALID_VECTOR_MESSAGE, code="ai_invalid_output")
    return [value / norm for value in vector]
