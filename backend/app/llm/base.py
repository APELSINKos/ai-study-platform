"""What the processing pipeline expects from analysis and embedding providers.

EMBEDDING_DIMENSIONS and Difficulty are defined by the models and only re-exported here,
so a provider takes everything it has to agree on from this module.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.llm.schemas import ChatAnswer, DocumentAnalysis
from app.models.chat_message import ChatMessageRole
from app.models.document import Difficulty, DocumentErrorCode
from app.models.document_chunk import EMBEDDING_DIMENSIONS

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "AnalysisRequest",
    "AnalysisResult",
    "ChatContextPassage",
    "ChatHistoryTurn",
    "ChatMessageRole",
    "ChatRequest",
    "ChatResult",
    "Difficulty",
    "EmbeddingProvider",
    "LLMProvider",
    "ProviderError",
    "ProviderRequestError",
    "ProviderRequestErrorCode",
    "ProviderUnavailableError",
]

# A refusal and an answer cut off by the token limit are both ai_invalid_output.
type ProviderRequestErrorCode = Literal[
    "ai_rejected", "ai_quota_exceeded", "ai_invalid_output", "embedding_dimension_mismatch"
]


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """What a model is shown of one document: its file name, heading outline and excerpts."""

    filename: str
    outline: str
    sample: str


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """An analysis with the model that wrote it and the tokens it took (zero offline)."""

    analysis: DocumentAnalysis
    model: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True, slots=True)
class ChatContextPassage:
    """One retrieved passage shown to the chat model under a server-assigned label (S1..Sn)."""

    label: str
    document_title: str
    heading: str | None
    page_start: int | None
    page_end: int | None
    content: str


@dataclass(frozen=True, slots=True)
class ChatHistoryTurn:
    """One prior turn of a chat session, passed for conversational continuity only."""

    role: ChatMessageRole
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """What the chat model is shown: the student's question, passages and recent turns."""

    question: str
    sources: tuple[ChatContextPassage, ...]
    history: tuple[ChatHistoryTurn, ...] = ()


@dataclass(frozen=True, slots=True)
class ChatResult:
    """A structured chat answer with the model that wrote it and the tokens it took."""

    answer: ChatAnswer
    model: str
    prompt_tokens: int
    completion_tokens: int


class LLMProvider(Protocol):
    """Analyses documents and answers chat questions; raises ProviderError when it cannot."""

    @property
    def model_name(self) -> str: ...

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult: ...

    def answer_question(
        self, request: ChatRequest, *, timeout_budget_seconds: float | None = None
    ) -> ChatResult: ...


class EmbeddingProvider(Protocol):
    """Turns each text into a unit vector of EMBEDDING_DIMENSIONS floats, in input order.

    Raises ProviderError when it cannot.
    """

    @property
    def model_name(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ProviderError(Exception):
    """A failed provider call, recorded on the document by its code; never an API error.

    transient tells whether a later attempt can succeed.
    """

    def __init__(
        self,
        message: str,
        *,
        code: DocumentErrorCode,
        transient: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.transient = transient
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailableError(ProviderError):
    """The provider could not be reached or was overloaded; trying again later may work."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(
            message, code="ai_unavailable", transient=True, retry_after_seconds=retry_after_seconds
        )


class ProviderRequestError(ProviderError):
    """The provider refused the request or answered unusably; repeating it will not help."""

    def __init__(self, message: str, *, code: ProviderRequestErrorCode) -> None:
        super().__init__(message, code=code, transient=False)
