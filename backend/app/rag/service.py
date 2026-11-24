"""Standalone Retrieval-Augmented Generation service for grounded Q&A.

Coordinates workspace passage retrieval, context budgeting, structured chat generation,
citation grounding and RAG/LLM Prometheus metrics. Deliberately free of HTTP, User and
ChatSession concerns so both the chat API and offline evaluation can call it directly.
"""

import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

import structlog

from app.core.metrics import LLM_REQUEST_DURATION, LLM_TOKENS, RETRIEVAL_DURATION
from app.core.timing import to_ms
from app.documents.cleaning import clean_text
from app.llm.base import (
    ChatHistoryTurn,
    ChatRequest,
    EmbeddingProvider,
    LLMProvider,
    ProviderError,
)
from app.rag.citations import INSUFFICIENT_CONTEXT_FALLBACK, CitationSnapshot, ground_answer
from app.rag.context import build_context
from app.rag.query import build_chat_keyword_query
from app.rag.retriever import CandidateSource, RetrievedChunk, Retriever
from app.rag.vector_store import SearchScope
from app.schemas.search import SearchMode

logger = structlog.get_logger(__name__)

CHAT_TOP_K: Final = 5
_QUERY_EMBEDDING_OPERATION: Final = "query_embedding"
_CHAT_OPERATION: Final = "chat"
_PROMPT_KIND: Final = "prompt"
_COMPLETION_KIND: Final = "completion"


def _noop() -> None:
    """Default transaction boundary hook when the caller does not manage DB transactions."""


def _default_clock() -> float:
    return time.perf_counter()


class RAGStore(CandidateSource, Protocol):
    """The vector-store queries RAGService needs; VectorStore satisfies this protocol."""

    def scope(
        self,
        workspace_id: uuid.UUID,
        *,
        embedding_model: str,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> SearchScope: ...


@dataclass(frozen=True, slots=True)
class RAGResult:
    """Grounded answer, immutable citations, retrieval trace, timings and token usage."""

    content: str
    citations: tuple[CitationSnapshot, ...]
    insufficient_context: bool
    grounding_overridden: bool
    retrieved_chunks: tuple[RetrievedChunk, ...]
    retrieval_mode: SearchMode
    semantic_available: bool
    skipped_llm: bool
    model: str | None
    embedding_ms: float | None
    retrieval_ms: float
    generation_ms: float
    prompt_tokens: int
    completion_tokens: int


class RAGService:
    """Retrieves relevant passages and generates a strictly grounded, cited answer."""

    def __init__(  # noqa: PLR0913 -- injected collaborators and scalar configuration
        self,
        store: RAGStore,
        embedder: EmbeddingProvider,
        llm: LLMProvider,
        *,
        embedding_model: str,
        min_similarity: float,
        turn_timeout_seconds: float,
        clock: Callable[[], float] = _default_clock,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._llm = llm
        self._embedding_model = embedding_model
        self._min_similarity = min_similarity
        self._turn_timeout_seconds = turn_timeout_seconds
        self._clock = clock

    def answer(  # noqa: PLR0913 -- standalone RAG entrypoint reused by evaluation
        self,
        workspace_id: uuid.UUID,
        question: str,
        *,
        document_ids: Sequence[uuid.UUID] | None = None,
        history: Sequence[ChatHistoryTurn] = (),
        mode: SearchMode = "hybrid",
        top_k: int = CHAT_TOP_K,
        min_similarity: float | None = None,
        scope: SearchScope | None = None,
        end_read_tx: Callable[[], None] = _noop,
    ) -> RAGResult:
        """Answer a question strictly from ready passages in workspace_id.

        Calls end_read_tx() after reading scope (when scope was not supplied) and again
        immediately after passage retrieval so no database transaction remains open during
        embedding or chat completion calls.
        """
        if top_k < 1:
            raise ValueError(f"top_k must be at least 1, got {top_k}")

        cleaned_question = " ".join(clean_text(question).split())
        if not cleaned_question:
            return _empty_result(
                retrieval_mode=mode,
                semantic_available=False,
                embedding_ms=None,
                retrieval_ms=0.0,
            )

        if scope is None:
            scope = self._store.scope(
                workspace_id,
                embedding_model=self._embedding_model,
                document_ids=document_ids,
            )
            end_read_tx()

        if scope.ready_documents == 0:
            return _empty_result(
                retrieval_mode=mode,
                semantic_available=False,
                embedding_ms=None,
                retrieval_ms=0.0,
            )

        deadline = self._clock() + self._turn_timeout_seconds
        embed_query = mode != "keyword" and scope.ready_documents > scope.stale_documents
        vector: list[float] | None = None
        embedding_ms: float | None = None
        if embed_query:
            vector, embedding_seconds = self._embed(workspace_id, cleaned_question, mode)
            embedding_ms = to_ms(embedding_seconds)

        keyword_query = (
            build_chat_keyword_query(cleaned_question, history=history) if mode != "vector" else ""
        )
        retrieval_mode = _effective_retrieval_mode(mode, has_vector=vector is not None)
        effective_min_similarity = (
            self._min_similarity if min_similarity is None else min_similarity
        )

        retrieval_started = self._clock()
        chunks = Retriever(self._store, min_similarity=effective_min_similarity).retrieve(
            workspace_id,
            keyword_query,
            vector,
            embedding_model=self._embedding_model,
            mode=retrieval_mode,
            limit=top_k,
            document_ids=document_ids,
        )
        end_read_tx()
        retrieval_seconds = max(0.0, self._clock() - retrieval_started)
        RETRIEVAL_DURATION.labels(mode=retrieval_mode).observe(retrieval_seconds)
        retrieval_ms = to_ms(retrieval_seconds)

        if not chunks:
            return _empty_result(
                retrieval_mode=retrieval_mode,
                semantic_available=vector is not None,
                embedding_ms=embedding_ms,
                retrieval_ms=retrieval_ms,
            )

        built = build_context(chunks)
        request = ChatRequest(
            question=cleaned_question,
            sources=built.to_chat_passages(),
            history=tuple(history),
        )
        remaining = max(0.0, deadline - self._clock())
        generation_started = self._clock()
        try:
            chat_result = self._llm.answer_question(request, timeout_budget_seconds=remaining)
        except ProviderError:
            generation_seconds = max(0.0, self._clock() - generation_started)
            _observe_llm_duration(_CHAT_OPERATION, "error", generation_seconds)
            raise
        generation_seconds = max(0.0, self._clock() - generation_started)
        _observe_llm_duration(_CHAT_OPERATION, "ok", generation_seconds)
        LLM_TOKENS.labels(operation=_CHAT_OPERATION, kind=_PROMPT_KIND).inc(
            chat_result.prompt_tokens
        )
        LLM_TOKENS.labels(operation=_CHAT_OPERATION, kind=_COMPLETION_KIND).inc(
            chat_result.completion_tokens
        )

        grounded = ground_answer(chat_result.answer, built)
        return RAGResult(
            content=grounded.content,
            citations=grounded.citations,
            insufficient_context=grounded.insufficient_context,
            grounding_overridden=grounded.grounding_overridden,
            retrieved_chunks=tuple(chunks),
            retrieval_mode=retrieval_mode,
            semantic_available=vector is not None,
            skipped_llm=False,
            model=chat_result.model,
            embedding_ms=embedding_ms,
            retrieval_ms=retrieval_ms,
            generation_ms=to_ms(generation_seconds),
            prompt_tokens=chat_result.prompt_tokens,
            completion_tokens=chat_result.completion_tokens,
        )

    def _embed(
        self, workspace_id: uuid.UUID, text: str, mode: SearchMode
    ) -> tuple[list[float] | None, float]:
        started = self._clock()
        try:
            [vector] = self._embedder.embed([text])
        except ProviderError as error:
            seconds = max(0.0, self._clock() - started)
            _observe_llm_duration(_QUERY_EMBEDDING_OPERATION, "error", seconds)
            logger.warning(
                "chat_embedding_failed",
                workspace_id=str(workspace_id),
                error_code=error.code,
            )
            if mode == "hybrid":
                return None, seconds
            raise
        seconds = max(0.0, self._clock() - started)
        _observe_llm_duration(_QUERY_EMBEDDING_OPERATION, "ok", seconds)
        return vector, seconds


def _effective_retrieval_mode(mode: SearchMode, *, has_vector: bool) -> SearchMode:
    if mode == "hybrid" and has_vector:
        return "hybrid"
    if mode == "vector":
        return "vector"
    return "keyword"


def _observe_llm_duration(
    operation: Literal["query_embedding", "chat"],
    outcome: Literal["ok", "error"],
    seconds: float,
) -> None:
    LLM_REQUEST_DURATION.labels(operation=operation, outcome=outcome).observe(seconds)


def _empty_result(
    *,
    retrieval_mode: SearchMode,
    semantic_available: bool,
    embedding_ms: float | None,
    retrieval_ms: float,
) -> RAGResult:
    return RAGResult(
        content=INSUFFICIENT_CONTEXT_FALLBACK,
        citations=(),
        insufficient_context=True,
        grounding_overridden=False,
        retrieved_chunks=(),
        retrieval_mode=retrieval_mode,
        semantic_available=semantic_available,
        skipped_llm=True,
        model=None,
        embedding_ms=embedding_ms,
        retrieval_ms=retrieval_ms,
        generation_ms=0.0,
        prompt_tokens=0,
        completion_tokens=0,
    )
