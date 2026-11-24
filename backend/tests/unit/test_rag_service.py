import json
import uuid
from collections.abc import Sequence
from typing import Any, Final

import pytest
from prometheus_client import REGISTRY

from app.core.logging import configure_logging
from app.llm.base import (
    AnalysisRequest,
    AnalysisResult,
    ChatHistoryTurn,
    ChatRequest,
    ChatResult,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.llm.schemas import ChatAnswer
from app.rag.citations import INSUFFICIENT_CONTEXT_FALLBACK
from app.rag.service import CHAT_TOP_K, RAGResult, RAGService
from app.rag.vector_store import ChunkHit, KeywordCandidate, SearchScope, VectorCandidate

_WORKSPACE_ID: Final = uuid.UUID("11111111-1111-4111-8111-111111111111")
_DOC_ID_1: Final = uuid.UUID("22222222-2222-4222-8222-222222222221")
_DOC_ID_2: Final = uuid.UUID("22222222-2222-4222-8222-222222222222")
_CHUNK_ID_1: Final = uuid.UUID("33333333-3333-4333-8333-333333333331")
_CHUNK_ID_2: Final = uuid.UUID("33333333-3333-4333-8333-333333333332")
_EMBEDDING_MODEL: Final = "mock-hashing-v1"
_CHAT_MODEL: Final = "test-chat-v1"
_LOG_KEYS: Final = {"event", "level", "logger", "timestamp"}
_DEFAULT_SCOPE: Final = SearchScope(ready_documents=2, stale_documents=0, pending_documents=0)


class _SteppingClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeStore:
    def __init__(  # noqa: PLR0913 -- test double with optional canned results and tracing hooks
        self,
        *,
        scope_result: SearchScope = _DEFAULT_SCOPE,
        nearest_results: list[VectorCandidate] | None = None,
        matching_results: list[KeywordCandidate] | None = None,
        hit_rows: list[ChunkHit] | None = None,
        events: list[str] | None = None,
        clock: _SteppingClock | None = None,
        retrieve_duration: float = 0.0,
    ) -> None:
        self.scope_result = scope_result
        self.nearest_results = nearest_results if nearest_results is not None else []
        self.matching_results = matching_results if matching_results is not None else []
        self.hit_rows = hit_rows if hit_rows is not None else []
        self.events = events if events is not None else []
        self._clock = clock
        self._retrieve_duration = retrieve_duration
        self.scope_calls: list[dict[str, object]] = []
        self.nearest_calls: list[dict[str, object]] = []
        self.matching_calls: list[dict[str, object]] = []
        self.hits_calls: list[dict[str, object]] = []

    def scope(
        self,
        workspace_id: uuid.UUID,
        *,
        embedding_model: str,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> SearchScope:
        self.events.append("scope")
        self.scope_calls.append(
            {
                "workspace_id": workspace_id,
                "embedding_model": embedding_model,
                "document_ids": None if document_ids is None else list(document_ids),
            }
        )
        return self.scope_result

    def nearest(
        self,
        workspace_id: uuid.UUID,
        vector: Sequence[float],
        *,
        embedding_model: str,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[VectorCandidate]:
        self.events.append("nearest")
        self.nearest_calls.append(
            {
                "workspace_id": workspace_id,
                "vector": list(vector),
                "embedding_model": embedding_model,
                "limit": limit,
                "document_ids": None if document_ids is None else list(document_ids),
            }
        )
        if self._clock is not None and self._retrieve_duration:
            self._clock.advance(self._retrieve_duration)
        return list(self.nearest_results)

    def matching(
        self,
        workspace_id: uuid.UUID,
        text: str,
        *,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[KeywordCandidate]:
        self.events.append("matching")
        self.matching_calls.append(
            {
                "workspace_id": workspace_id,
                "text": text,
                "limit": limit,
                "document_ids": None if document_ids is None else list(document_ids),
            }
        )
        if self._clock is not None and self._retrieve_duration and not self.nearest_calls:
            self._clock.advance(self._retrieve_duration)
        return list(self.matching_results)

    def hits(
        self, workspace_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID], text: str
    ) -> list[ChunkHit]:
        self.events.append("hits")
        self.hits_calls.append(
            {"workspace_id": workspace_id, "chunk_ids": list(chunk_ids), "text": text}
        )
        wanted = set(chunk_ids)
        return [hit for hit in self.hit_rows if hit.chunk_id in wanted]


class _FakeEmbedder:
    def __init__(
        self,
        *,
        vector: list[float] | None = None,
        error: Exception | None = None,
        events: list[str] | None = None,
        clock: _SteppingClock | None = None,
        duration: float = 0.0,
    ) -> None:
        self.vector = vector if vector is not None else [1.0, 0.0]
        self.error = error
        self.events = events if events is not None else []
        self._clock = clock
        self._duration = duration
        self.calls: list[list[str]] = []

    @property
    def model_name(self) -> str:
        return _EMBEDDING_MODEL

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.events.append("embed")
        self.calls.append(list(texts))
        if self._clock is not None and self._duration:
            self._clock.advance(self._duration)
        if self.error is not None:
            raise self.error
        return [list(self.vector) for _ in texts]


class _FakeLLM:
    def __init__(
        self,
        *,
        result: ChatResult | None = None,
        error: Exception | None = None,
        events: list[str] | None = None,
        clock: _SteppingClock | None = None,
        duration: float = 0.0,
    ) -> None:
        self.result = result or ChatResult(
            answer=ChatAnswer(
                answer="Spaced review slows forgetting [S1].",
                citations=["S1"],
                insufficient_context=False,
            ),
            model=_CHAT_MODEL,
            prompt_tokens=120,
            completion_tokens=35,
        )
        self.error = error
        self.events = events if events is not None else []
        self._clock = clock
        self._duration = duration
        self.requests: list[ChatRequest] = []
        self.timeout_budgets: list[float | None] = []

    @property
    def model_name(self) -> str:
        return _CHAT_MODEL

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult:
        raise NotImplementedError

    def answer_question(
        self, request: ChatRequest, *, timeout_budget_seconds: float | None = None
    ) -> ChatResult:
        self.events.append("llm")
        self.requests.append(request)
        self.timeout_budgets.append(timeout_budget_seconds)
        if self._clock is not None and self._duration:
            self._clock.advance(self._duration)
        if self.error is not None:
            raise self.error
        return self.result


def _hit(chunk_id: uuid.UUID = _CHUNK_ID_1, document_id: uuid.UUID = _DOC_ID_1) -> ChunkHit:
    return ChunkHit(
        chunk_id=chunk_id,
        document_id=document_id,
        document_title="Forgetting curve",
        chunk_index=0,
        heading="Spaced repetition",
        page_start=None,
        page_end=None,
        content="Each review makes the next loss slower than the one before.",
        char_count=59,
        headline="\x01review\x02 makes the next loss slower",
    )


def _metric_snapshot() -> dict[str, float]:
    keys: dict[str, tuple[str, dict[str, str]]] = {
        "retrieval_hybrid": ("retrieval_duration_seconds_count", {"mode": "hybrid"}),
        "retrieval_vector": ("retrieval_duration_seconds_count", {"mode": "vector"}),
        "retrieval_keyword": ("retrieval_duration_seconds_count", {"mode": "keyword"}),
        "embed_ok": (
            "llm_request_duration_seconds_count",
            {"operation": "query_embedding", "outcome": "ok"},
        ),
        "embed_error": (
            "llm_request_duration_seconds_count",
            {"operation": "query_embedding", "outcome": "error"},
        ),
        "chat_ok": (
            "llm_request_duration_seconds_count",
            {"operation": "chat", "outcome": "ok"},
        ),
        "chat_error": (
            "llm_request_duration_seconds_count",
            {"operation": "chat", "outcome": "error"},
        ),
        "tokens_prompt": ("llm_tokens_total", {"operation": "chat", "kind": "prompt"}),
        "tokens_completion": ("llm_tokens_total", {"operation": "chat", "kind": "completion"}),
    }
    return {
        name: REGISTRY.get_sample_value(metric, labels) or 0.0
        for name, (metric, labels) in keys.items()
    }


def _deltas(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    return {key: after[key] - before[key] for key in before if after[key] != before[key]}


def _events(output: str, event: str) -> list[dict[str, Any]]:
    lines = [json.loads(line) for line in output.splitlines() if line.strip()]
    return [line for line in lines if line["event"] == event]


def test_hybrid_answer_runs_full_pipeline_ends_transactions_and_records_metrics() -> None:
    events: list[str] = []
    clock = _SteppingClock()
    store = _FakeStore(
        nearest_results=[VectorCandidate(_CHUNK_ID_1, _DOC_ID_1, distance=0.2)],
        matching_results=[KeywordCandidate(_CHUNK_ID_1, _DOC_ID_1, rank=0.8)],
        hit_rows=[_hit()],
        events=events,
        clock=clock,
        retrieve_duration=0.15,
    )
    embedder = _FakeEmbedder(events=events, clock=clock, duration=1.25)
    llm = _FakeLLM(events=events, clock=clock, duration=2.5)
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=23.0,
        clock=clock,
    )
    history = (ChatHistoryTurn(role="user", content="Tell me about forgetting."),)
    before = _metric_snapshot()

    result = service.answer(
        _WORKSPACE_ID,
        "  How does review\n slow down forgetting?  ",
        document_ids=[_DOC_ID_1],
        history=history,
        end_read_tx=lambda: events.append("end_read_tx"),
    )

    after = _metric_snapshot()
    assert isinstance(result, RAGResult)
    assert result.content == "Spaced review slows forgetting [1]."
    assert len(result.citations) == 1
    assert result.citations[0].index == 1
    assert result.citations[0].chunk_id == _CHUNK_ID_1
    assert result.insufficient_context is False
    assert result.grounding_overridden is False
    assert len(result.retrieved_chunks) == 1
    assert result.retrieval_mode == "hybrid"
    assert result.semantic_available is True
    assert result.skipped_llm is False
    assert result.model == _CHAT_MODEL
    assert result.embedding_ms == pytest.approx(1250.0)
    assert result.retrieval_ms == pytest.approx(150.0)
    assert result.generation_ms == pytest.approx(2500.0)
    assert (result.prompt_tokens, result.completion_tokens) == (120, 35)
    assert events == [
        "scope",
        "end_read_tx",
        "embed",
        "nearest",
        "matching",
        "hits",
        "end_read_tx",
        "llm",
    ]
    assert embedder.calls == [["How does review slow down forgetting?"]]
    assert store.matching_calls[0]["text"] == "review or slow or forgetting"
    assert store.scope_calls[0]["document_ids"] == [_DOC_ID_1]
    assert store.nearest_calls[0]["document_ids"] == [_DOC_ID_1]
    assert store.matching_calls[0]["document_ids"] == [_DOC_ID_1]
    assert llm.requests[0].question == "How does review slow down forgetting?"
    assert llm.requests[0].history == history
    # Turn budget 23.0 - 1.25 (embed) - 0.15 (retrieve) = 21.6 s forwarded to LLM.
    assert llm.timeout_budgets == [pytest.approx(21.6)]
    assert _deltas(before, after) == {
        "retrieval_hybrid": 1.0,
        "embed_ok": 1.0,
        "chat_ok": 1.0,
        "tokens_prompt": 120.0,
        "tokens_completion": 35.0,
    }


def test_presupplied_scope_skips_scope_query_and_calls_end_read_tx_once_after_retrieval() -> None:
    events: list[str] = []
    store = _FakeStore(
        nearest_results=[VectorCandidate(_CHUNK_ID_1, _DOC_ID_1, distance=0.1)],
        hit_rows=[_hit()],
        events=events,
    )
    embedder = _FakeEmbedder(events=events)
    llm = _FakeLLM(events=events)
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )

    result = service.answer(
        _WORKSPACE_ID,
        "What does review do?",
        scope=SearchScope(ready_documents=1, stale_documents=0, pending_documents=0),
        end_read_tx=lambda: events.append("end_read_tx"),
    )

    assert result.skipped_llm is False
    assert store.scope_calls == []
    assert events == ["embed", "nearest", "matching", "hits", "end_read_tx", "llm"]


def test_keyword_mode_skips_embedding_and_uses_keyword_retrieval() -> None:
    events: list[str] = []
    store = _FakeStore(
        matching_results=[KeywordCandidate(_CHUNK_ID_1, _DOC_ID_1, rank=0.5)],
        hit_rows=[_hit()],
        events=events,
    )
    embedder = _FakeEmbedder(events=events)
    llm = _FakeLLM(events=events)
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )
    before = _metric_snapshot()

    result = service.answer(
        _WORKSPACE_ID,
        "Explain forgetting curve",
        mode="keyword",
        end_read_tx=lambda: events.append("end_read_tx"),
    )

    after = _metric_snapshot()
    assert embedder.calls == []
    assert store.nearest_calls == []
    assert result.retrieval_mode == "keyword"
    assert result.semantic_available is False
    assert result.embedding_ms is None
    assert result.skipped_llm is False
    assert _deltas(before, after) == {
        "retrieval_keyword": 1.0,
        "chat_ok": 1.0,
        "tokens_prompt": 120.0,
        "tokens_completion": 35.0,
    }


def test_vector_mode_skips_keyword_matching_and_embeds_full_question() -> None:
    events: list[str] = []
    store = _FakeStore(
        nearest_results=[VectorCandidate(_CHUNK_ID_1, _DOC_ID_1, distance=0.25)],
        hit_rows=[_hit()],
        events=events,
    )
    embedder = _FakeEmbedder(events=events)
    llm = _FakeLLM(events=events)
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )
    before = _metric_snapshot()

    result = service.answer(
        _WORKSPACE_ID,
        "Explain spaced repetition",
        mode="vector",
        end_read_tx=lambda: events.append("end_read_tx"),
    )

    after = _metric_snapshot()
    assert store.matching_calls == []
    assert store.hits_calls[0]["text"] == ""
    assert result.retrieval_mode == "vector"
    assert result.semantic_available is True
    assert result.skipped_llm is False
    assert _deltas(before, after) == {
        "retrieval_vector": 1.0,
        "embed_ok": 1.0,
        "chat_ok": 1.0,
        "tokens_prompt": 120.0,
        "tokens_completion": 35.0,
    }


@pytest.mark.parametrize(
    "question",
    ["", "   \n\t ", "\x1f\u200b", "\u202e", "\u00ad", "\u202e\u00ad\x1b"],
)
def test_blank_question_short_circuits_without_store_provider_or_metrics(question: str) -> None:
    events: list[str] = []
    store = _FakeStore(events=events)
    embedder = _FakeEmbedder(events=events)
    llm = _FakeLLM(events=events)
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )
    before = _metric_snapshot()

    result = service.answer(
        _WORKSPACE_ID,
        question,
        end_read_tx=lambda: events.append("end_read_tx"),
    )

    after = _metric_snapshot()
    assert result == RAGResult(
        content=INSUFFICIENT_CONTEXT_FALLBACK,
        citations=(),
        insufficient_context=True,
        grounding_overridden=False,
        retrieved_chunks=(),
        retrieval_mode="hybrid",
        semantic_available=False,
        skipped_llm=True,
        model=None,
        embedding_ms=None,
        retrieval_ms=0.0,
        generation_ms=0.0,
        prompt_tokens=0,
        completion_tokens=0,
    )
    assert events == []
    assert _deltas(before, after) == {}


def test_question_cleaning_strips_format_controls_and_normalizes_ligatures() -> None:
    store = _FakeStore(
        nearest_results=[VectorCandidate(_CHUNK_ID_1, _DOC_ID_1, distance=0.1)],
        matching_results=[KeywordCandidate(_CHUNK_ID_1, _DOC_ID_1, rank=0.7)],
        hit_rows=[_hit()],
    )
    embedder = _FakeEmbedder()
    llm = _FakeLLM()
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )

    service.answer(_WORKSPACE_ID, "ﬁle\u202e\u00ad   review\x1b")

    assert embedder.calls == [["file review"]]
    assert llm.requests[0].question == "file review"


def test_empty_scope_short_circuits_before_embedding_retrieval_and_llm() -> None:
    events: list[str] = []
    store = _FakeStore(
        scope_result=SearchScope(ready_documents=0, stale_documents=0, pending_documents=2),
        events=events,
    )
    embedder = _FakeEmbedder(events=events)
    llm = _FakeLLM(events=events)
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )
    before = _metric_snapshot()

    result = service.answer(
        _WORKSPACE_ID,
        "How does review work?",
        end_read_tx=lambda: events.append("end_read_tx"),
    )

    after = _metric_snapshot()
    assert result.skipped_llm is True
    assert result.insufficient_context is True
    assert result.model is None
    assert result.content == INSUFFICIENT_CONTEXT_FALLBACK
    assert events == ["scope", "end_read_tx"]
    assert _deltas(before, after) == {}


def test_empty_retrieval_short_circuits_llm_with_zero_chat_or_token_metrics() -> None:
    events: list[str] = []
    store = _FakeStore(
        nearest_results=[VectorCandidate(_CHUNK_ID_1, _DOC_ID_1, distance=0.99)],
        matching_results=[],
        hit_rows=[_hit()],
        events=events,
    )
    embedder = _FakeEmbedder(events=events)
    llm = _FakeLLM(events=events)
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.5,
        turn_timeout_seconds=20.0,
    )
    before = _metric_snapshot()

    result = service.answer(
        _WORKSPACE_ID,
        "Chocolate xylophone soup",
        end_read_tx=lambda: events.append("end_read_tx"),
    )

    after = _metric_snapshot()
    assert result.skipped_llm is True
    assert result.insufficient_context is True
    assert result.grounding_overridden is False
    assert result.model is None
    assert result.citations == ()
    assert result.retrieved_chunks == ()
    assert result.semantic_available is True
    assert result.generation_ms == 0.0
    assert (result.prompt_tokens, result.completion_tokens) == (0, 0)
    assert llm.requests == []
    assert events == ["scope", "end_read_tx", "embed", "nearest", "matching", "end_read_tx"]
    assert _deltas(before, after) == {"retrieval_hybrid": 1.0, "embed_ok": 1.0}


def test_stale_only_documents_skip_embedding_and_degrade_hybrid_to_keyword() -> None:
    store = _FakeStore(
        scope_result=SearchScope(ready_documents=2, stale_documents=2, pending_documents=0),
        matching_results=[KeywordCandidate(_CHUNK_ID_1, _DOC_ID_1, rank=0.6)],
        hit_rows=[_hit()],
    )
    embedder = _FakeEmbedder()
    llm = _FakeLLM()
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )

    result = service.answer(_WORKSPACE_ID, "Spaced repetition")

    assert embedder.calls == []
    assert store.nearest_calls == []
    assert result.retrieval_mode == "keyword"
    assert result.semantic_available is False
    assert result.embedding_ms is None
    assert result.skipped_llm is False


def test_embedding_failure_in_hybrid_degrades_to_keyword_and_logs_safe_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    store = _FakeStore(
        matching_results=[KeywordCandidate(_CHUNK_ID_1, _DOC_ID_1, rank=0.7)],
        hit_rows=[_hit()],
    )
    embedder = _FakeEmbedder(error=ProviderUnavailableError("secret raw upstream failure details"))
    llm = _FakeLLM()
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )
    before = _metric_snapshot()

    result = service.answer(_WORKSPACE_ID, "quorvex spaced repetition")

    after = _metric_snapshot()
    assert result.retrieval_mode == "keyword"
    assert result.semantic_available is False
    assert result.skipped_llm is False
    assert result.embedding_ms is not None
    assert store.nearest_calls == []
    assert len(store.matching_calls) == 1
    output = capsys.readouterr().out
    [warning] = _events(output, "chat_embedding_failed")
    assert warning["level"] == "warning"
    assert warning["workspace_id"] == str(_WORKSPACE_ID)
    assert warning["error_code"] == "ai_unavailable"
    assert set(warning) == {*_LOG_KEYS, "workspace_id", "error_code"}
    assert "quorvex" not in output.lower()
    assert "upstream failure" not in output.lower()
    assert _deltas(before, after) == {
        "retrieval_keyword": 1.0,
        "embed_error": 1.0,
        "chat_ok": 1.0,
        "tokens_prompt": 120.0,
        "tokens_completion": 35.0,
    }


def test_embedding_failure_in_vector_mode_propagates_without_retrieval_or_llm() -> None:
    store = _FakeStore()
    embedder = _FakeEmbedder(
        error=ProviderRequestError("Quota exhausted", code="ai_quota_exceeded")
    )
    llm = _FakeLLM()
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )
    before = _metric_snapshot()

    with pytest.raises(ProviderRequestError) as exc_info:
        service.answer(_WORKSPACE_ID, "Spaced repetition", mode="vector")

    after = _metric_snapshot()
    assert exc_info.value.code == "ai_quota_exceeded"
    assert store.nearest_calls == []
    assert store.matching_calls == []
    assert llm.requests == []
    assert _deltas(before, after) == {"embed_error": 1.0}


def test_timeout_budget_is_clamped_to_zero_when_embedding_and_retrieval_exhaust_turn() -> None:
    clock = _SteppingClock()
    store = _FakeStore(
        nearest_results=[VectorCandidate(_CHUNK_ID_1, _DOC_ID_1, distance=0.1)],
        hit_rows=[_hit()],
        clock=clock,
        retrieve_duration=2.0,
    )
    embedder = _FakeEmbedder(clock=clock, duration=5.0)
    llm = _FakeLLM(clock=clock, duration=0.5)
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=6.0,
        clock=clock,
    )

    service.answer(_WORKSPACE_ID, "Spaced repetition")

    assert llm.timeout_budgets == [0.0]


def test_grounding_override_discards_ungrounded_prose_and_preserves_usage() -> None:
    store = _FakeStore(
        matching_results=[KeywordCandidate(_CHUNK_ID_1, _DOC_ID_1, rank=0.8)],
        hit_rows=[_hit()],
    )
    embedder = _FakeEmbedder()
    llm = _FakeLLM(
        result=ChatResult(
            answer=ChatAnswer(
                answer="Invented claim [S99].",
                citations=["S99"],
                insufficient_context=False,
            ),
            model=_CHAT_MODEL,
            prompt_tokens=90,
            completion_tokens=15,
        )
    )
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )

    result = service.answer(_WORKSPACE_ID, "Spaced repetition", mode="keyword")

    assert result.content == INSUFFICIENT_CONTEXT_FALLBACK
    assert result.citations == ()
    assert result.insufficient_context is True
    assert result.grounding_overridden is True
    assert result.skipped_llm is False
    assert result.model == _CHAT_MODEL
    assert (result.prompt_tokens, result.completion_tokens) == (90, 15)


def test_llm_provider_error_records_chat_error_metric_without_tokens_and_propagates() -> None:
    store = _FakeStore(
        matching_results=[KeywordCandidate(_CHUNK_ID_1, _DOC_ID_1, rank=0.8)],
        hit_rows=[_hit()],
    )
    embedder = _FakeEmbedder()
    llm = _FakeLLM(error=ProviderUnavailableError("Model overloaded", retry_after_seconds=12.0))
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )
    before = _metric_snapshot()

    with pytest.raises(ProviderUnavailableError) as exc_info:
        service.answer(_WORKSPACE_ID, "Spaced repetition", mode="keyword")

    after = _metric_snapshot()
    assert exc_info.value.retry_after_seconds == 12.0
    assert _deltas(before, after) == {"retrieval_keyword": 1.0, "chat_error": 1.0}


def test_short_followup_augments_keyword_query_from_prior_user_turn() -> None:
    store = _FakeStore(
        matching_results=[KeywordCandidate(_CHUNK_ID_1, _DOC_ID_1, rank=0.5)],
        hit_rows=[_hit()],
    )
    embedder = _FakeEmbedder()
    llm = _FakeLLM()
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )
    history = (
        ChatHistoryTurn(role="user", content="Explain normalization anomalies"),
        ChatHistoryTurn(role="assistant", content="There are three anomaly types [1]."),
    )

    service.answer(_WORKSPACE_ID, "Why?", history=history, mode="keyword")

    assert store.matching_calls[0]["text"] == "normalization or anomalies"


def test_per_call_min_similarity_override_and_top_k_validation() -> None:
    store = _FakeStore(
        nearest_results=[
            VectorCandidate(_CHUNK_ID_1, _DOC_ID_1, distance=0.1),
            VectorCandidate(_CHUNK_ID_2, _DOC_ID_2, distance=0.5),
        ],
        hit_rows=[_hit(_CHUNK_ID_1, _DOC_ID_1), _hit(_CHUNK_ID_2, _DOC_ID_2)],
    )
    embedder = _FakeEmbedder()
    llm = _FakeLLM()
    service = RAGService(
        store,
        embedder,
        llm,
        embedding_model=_EMBEDDING_MODEL,
        min_similarity=0.05,
        turn_timeout_seconds=20.0,
    )

    assert CHAT_TOP_K == 5
    result = service.answer(_WORKSPACE_ID, "review", mode="vector", min_similarity=0.8)
    assert [chunk.chunk_id for chunk in result.retrieved_chunks] == [_CHUNK_ID_1]

    with pytest.raises(ValueError, match="top_k"):
        service.answer(_WORKSPACE_ID, "review", top_k=0)
