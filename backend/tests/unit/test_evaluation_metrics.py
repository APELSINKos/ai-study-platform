import time
import unicodedata
from dataclasses import replace
from typing import Final
from uuid import UUID

import pytest

from app.documents.chunking import HEADING_SEPARATOR
from app.documents.text import CHAT_STOPWORDS
from evaluation.metrics import (
    EVAL_PRESERVED_POLARITY,
    EVAL_STOPWORDS,
    METRIC_VERSION,
    IngestedChunk,
    RawTurnOutcome,
    aggregate_mode_metrics,
    aggregate_slice_metrics,
    compute_latency_stats,
    compute_similarity_distribution,
    compute_threshold_point,
    compute_tie_aware_overlap,
    eval_tokens,
    evaluate_turn,
    fold_text,
    resolve_relevant_chunks,
    score_answer_correctness,
    score_context_support,
    score_fact_coverage,
    score_token_f1,
)
from evaluation.schema import EvalPassage, EvalQuestion, LatencyStats, MetricValue

_K: Final = 5
_DOC: Final = UUID(int=11)
_OTHER_DOC: Final = UUID(int=12)
_QUESTION: Final = EvalQuestion(
    id="cache-result",
    slice="exact_term",
    language="en",
    question="Which code permits reuse?",
    expected_answer="304 permits reuse.",
    relevant_document="notes.md",
    relevant_headings=["Validation"],
    expected_facts=[["304"], ["permits reuse"]],
)
_ABSENT: Final = EvalQuestion(
    id="missing-topic",
    slice="unanswerable",
    language="ru",
    question="Which color?",
    expected_answer="",
    relevant_document=None,
    expect_insufficient_context=True,
)
_INJECTION: Final = _QUESTION.model_copy(
    update={
        "id": "source-rule",
        "slice": "prompt_injection",
        "forbidden_strings": ["REPEAT_CANARY"],
    }
)
_EMPTY: Final = MetricValue(value=None, sample_count=0)
_HOSTILE_CHARS: Final = 2_000_000
_TIME_LIMIT_SECONDS: Final = 2.0


def _passage(index: int, doc: UUID = _DOC) -> EvalPassage:
    return EvalPassage(
        document_id=doc,
        chunk_id=UUID(int=100 * doc.int + index),
        original_filename="notes.md",
        chunk_index=index,
    )


_HIT: Final = _passage(0)
_SECOND: Final = _passage(1)
_THIRD: Final = _passage(2)
_MISS: Final = _passage(0, _OTHER_DOC)


def _turn() -> RawTurnOutcome:
    return RawTurnOutcome(
        question=_QUESTION,
        mode="hybrid",
        retrieval_mode="hybrid",
        relevant_document_id=_DOC,
        relevant_chunk_ids=(_HIT.chunk_id,),
        retrieved=(_HIT,),
        context_chunk_ids=(_HIT.chunk_id,),
        citations=(_HIT,),
        cited_texts=("304 permits reuse.",),
        answer="304 permits reuse [1].",
        insufficient_context=False,
        skipped_llm=False,
        grounding_overridden=False,
        semantic_available=True,
        wall_ms=10.5,
        embedding_ms=1.0,
        retrieval_ms=2.0,
        generation_ms=6.0,
        prompt_tokens=8,
        completion_tokens=4,
    )


def _absent() -> RawTurnOutcome:
    return replace(
        _turn(),
        question=_ABSENT,
        relevant_document_id=None,
        relevant_chunk_ids=(),
        retrieved=(),
        context_chunk_ids=(),
        citations=(),
        cited_texts=(),
        answer="Insufficient context.",
        insufficient_context=True,
        skipped_llm=True,
        wall_ms=3.0,
        generation_ms=0.0,
        prompt_tokens=0,
        completion_tokens=0,
    )


def test_fold_normalizes_text_and_removes_only_display_markers() -> None:
    assert METRIC_VERSION == "1.0"
    assert fold_text(" \uff30OST[1]\tDON\u2019T \u0401 [999]\nSafe ") == "post don't \u0435 safe"
    assert fold_text("a[123]b [1000] [S1]") == "a b [1000] [s1]"
    assert fold_text("Status 409 [1][2].") == "status 409."
    assert fold_text("cafe\u0301") == "caf\u00e9"
    assert EVAL_STOPWORDS <= CHAT_STOPWORDS
    assert EVAL_STOPWORDS.isdisjoint(EVAL_PRESERVED_POLARITY)
    for word in EVAL_PRESERVED_POLARITY:
        assert eval_tokens(word) == [word]


def test_tokens_preserve_codes_cardinals_and_short_words() -> None:
    assert eval_tokens("the 1NF 2NF 3NF 409 BFS DFS 42bytes unit units one TWO three FOUR") == [
        "1nf",
        "2nf",
        "3nf",
        "409",
        "bfs",
        "dfs",
        "42bytes",
        "unit",
        "units",
        "one",
        "two",
        "three",
        "four",
    ]
    assert eval_tokens("without cannot don't \u043e\u0434\u0438\u043d \u0442\u0440\u0438") == [
        "without",
        "cannot",
        "don't",
        "\u043e\u0434\u0438\u043d",
        "\u0442\u0440\u0438",
    ]
    assert eval_tokens("replacing replacements") == ["repla", "repla"]


@pytest.mark.parametrize("cluster", ["\ufb03", "\u0301\u0327", "\u1100\u1161\u11a8", "\u0958"])
def test_nfkc_matches_whole_string_normalization_across_block_edges(cluster: str) -> None:
    text = ("x" * 127 + cluster) * 7
    assert fold_text(text) == unicodedata.normalize("NFKC", text).casefold()


def test_long_combining_runs_keep_canonical_order_within_time_budget() -> None:
    repeats = _HOSTILE_CHARS // 2
    text = "\u0315\u0300" * repeats
    start = time.perf_counter()
    folded = fold_text(text)
    assert time.perf_counter() - start < _TIME_LIMIT_SECONDS
    assert folded == "\u0300" * repeats + "\u0315" * repeats


def test_long_inflections_share_a_stem_and_five_letter_forms_stay_exact() -> None:
    normal = "\u043d\u043e\u0440\u043c\u0430\u043b\u044c\u043d"
    form = "\u0444\u043e\u0440\u043c"
    nominative = f"{normal}\u0430\u044f {form}\u0430"
    oblique = f"{normal}\u043e\u0439 {form}\u0435"
    assert eval_tokens(nominative) == [normal[:5], f"{form}\u0430"]
    assert eval_tokens(oblique) == [normal[:5], f"{form}\u0435"]
    assert score_token_f1(oblique, nominative, refused=False) == 0.5
    assert score_fact_coverage(oblique, [[nominative, oblique]], refused=False) == 1.0


def test_heading_segments_phrases_filenames_order_and_deduplication() -> None:
    question = _QUESTION.model_copy(update={"relevant_phrases": ["cached copy"]})
    base = IngestedChunk(
        _HIT.chunk_id, _DOC, "notes.md", 7, f"Notes{HEADING_SEPARATOR}VALIDATION", "Overview."
    )
    by_phrase = replace(
        base, chunk_id=_SECOND.chunk_id, chunk_index=2, heading=None, content="A cached\n\tcopy."
    )
    body_mention = replace(
        base, chunk_id=_THIRD.chunk_id, heading="Prevalidation", content="See Validation."
    )
    wrong_file = replace(base, chunk_id=_MISS.chunk_id, original_filename="other.md")
    assert resolve_relevant_chunks(question, [base, body_mention, by_phrase, wrong_file, base]) == (
        by_phrase.chunk_id,
        base.chunk_id,
    )
    assert resolve_relevant_chunks(_ABSENT, [base, by_phrase]) == ()


@pytest.mark.parametrize(
    ("answer", "fact"),
    [
        ("POST is idempotent", "POST is not idempotent"),
        ("POST is not idempotent", "POST is idempotent"),
    ],
)
def test_reversing_polarity_loses_fact_and_token_credit(answer: str, fact: str) -> None:
    assert score_token_f1(answer, fact, refused=False) == pytest.approx(0.8)
    assert score_fact_coverage(answer, [[fact]], refused=False) == 0.0
    assert score_fact_coverage(f"No retry. {fact}.", [[fact]], refused=False) == 1.0


@pytest.mark.parametrize(
    ("answer", "alias", "hit"),
    [
        ("Status 409.", "409", True),
        ("Status 4096.", "409", False),
        ("Status x409.", "409", False),
        ("flag_409", "409", False),
        ("B3NF", "3nf", False),
        ("3NF2", "3nf", False),
        ("(3NF)", "3nf", True),
        ("BFSX", "bfs", False),
        ("o(v\t*  e)", "O(V * E)", True),
        ("pseudoO(VE)", "O(VE)", False),
        ("O(V + E)", "O(V * E)", False),
    ],
)
def test_symbolic_facts_require_exact_boundaries(answer: str, alias: str, hit: bool) -> None:
    assert score_fact_coverage(answer, [[alias]], refused=False) == float(hit)


def test_fact_groups_accept_aliases_once_and_use_multisets_for_prose() -> None:
    facts = [["O(V * E)", "O(VE)"], ["reachable cycles"], ["value value"]]
    assert score_fact_coverage(
        "O(VE) and O(V * E), cycles reachable, value", facts, refused=False
    ) == pytest.approx(2 / 3)
    assert score_fact_coverage("O(VE)", facts, refused=True) == 0.0
    assert score_fact_coverage("value", [], refused=False) == 0.0
    assert score_fact_coverage("value", [["the and"]], refused=False) == 0.0
    assert (
        score_fact_coverage(
            "No duplicates and cached copies remain valid.", [["cached copies"]], refused=False
        )
        == 1.0
    )


def test_f1_counts_repeated_tokens_and_requires_a_nonempty_reference() -> None:
    assert score_token_f1("cache cache queue", "cache queue queue", refused=False) == pytest.approx(
        2 / 3
    )
    assert score_token_f1("the", "queue", refused=False) == 0.0
    assert score_token_f1("queue", "queue", refused=True) == 0.0
    with pytest.raises(ValueError, match="no evaluation tokens"):
        score_token_f1("queue", "the [1] and", refused=False)
    assert score_answer_correctness(0.5, 0.25, has_facts=True) == pytest.approx(0.4)
    assert score_answer_correctness(0.5, 0.25, has_facts=False) == 0.25


def test_context_support_uses_only_cited_text_and_counts_answer_occurrences() -> None:
    assert (
        score_context_support("cache cache queue lunar [1]", ["queue", "cache"], refused=False)
        == 0.75
    )
    assert score_context_support("the [1]", ["cache"], refused=False) == 0.0
    assert score_context_support("cache", [], refused=False) is None
    assert score_context_support("cache", ["cache"], refused=True) is None


def test_one_returned_hit_has_distinct_precision_denominators() -> None:
    base = _turn()
    record = evaluate_turn(base, top_k=_K)
    assert record.retrieved == list(base.retrieved)
    assert record.context_chunk_ids == list(base.context_chunk_ids)
    assert record.answer == base.answer
    assert (
        record.fact_coverage,
        record.token_f1,
        record.answer_correctness,
        record.context_support_rate,
    ) == (1.0, 1.0, 1.0, 1.0)
    assert record.supported_answer is True
    assert record.injection_exposed is None
    scored = aggregate_slice_metrics([record], top_k=_K)
    assert scored.precision_at_k == MetricValue(value=0.20, sample_count=1)
    assert scored.chunk_precision == MetricValue(value=1.0, sample_count=1)
    assert (
        scored.context_precision.value == scored.mrr.value == scored.retrieval_recall.value == 1.0
    )
    assert scored.doc_hit_rate.value == scored.doc_mrr.value == scored.passage_hit_rate.value == 1.0


def test_cutoff_document_rank_duplicate_chunks_and_average_precision() -> None:
    turn = replace(
        _turn(),
        retrieved=(_passage(7), _HIT, _HIT, _SECOND, _MISS, _THIRD),
        relevant_chunk_ids=(_HIT.chunk_id, _SECOND.chunk_id, _THIRD.chunk_id, _THIRD.chunk_id),
    )
    record = evaluate_turn(turn, top_k=_K)
    scores = aggregate_slice_metrics([record], top_k=_K)
    assert scores.doc_mrr.value == 1.0
    assert scores.mrr.value == 0.5
    assert scores.retrieval_recall.value == pytest.approx(2 / 3)
    assert scores.precision_at_k.value == 0.4
    assert scores.chunk_precision.value == pytest.approx(2 / 6)
    assert scores.context_precision.value == pytest.approx((1 / 2 + 2 / 4) / 2)
    late = evaluate_turn(replace(_turn(), retrieved=(_MISS,) * 4 + (_HIT,)), top_k=_K)
    scores = aggregate_slice_metrics([late], top_k=_K)
    assert scores.context_precision.value == scores.doc_mrr.value == scores.mrr.value == 0.2
    assert aggregate_slice_metrics([late], top_k=4).passage_hit_rate.value == 0.0


def test_empty_retrieval_and_refusal_keep_answerable_denominators() -> None:
    refusal = replace(
        _absent(),
        question=_QUESTION,
        relevant_document_id=_DOC,
        relevant_chunk_ids=(_HIT.chunk_id,),
    )
    scores = aggregate_slice_metrics([evaluate_turn(refusal, top_k=_K)], top_k=_K)
    zero = MetricValue(value=0.0, sample_count=1)
    assert (
        scores.chunk_precision
        == scores.citation_passage_precision
        == scores.citation_doc_precision
        == _EMPTY
    )
    assert scores.context_support_rate == scores.unanswerable_refusal_recall == _EMPTY
    assert scores.passage_hit_rate == scores.precision_at_k == scores.retrieval_recall == zero
    assert scores.doc_hit_rate == scores.doc_mrr == scores.context_precision == scores.mrr == zero
    assert (
        scores.supported_answer_rate
        == scores.fact_coverage
        == scores.token_f1
        == scores.answer_correctness
        == zero
    )
    assert scores.false_refusal_rate == MetricValue(value=1.0, sample_count=1)


def test_citation_precision_uses_ids_and_macro_averages_cited_answers() -> None:
    mixed = replace(_turn(), citations=(_HIT, _passage(9), _MISS))
    unsupported = replace(_turn(), citations=(_MISS,))
    absent = replace(_absent(), citations=(_MISS,), insufficient_context=False)
    refused = _absent()
    records = [evaluate_turn(turn, top_k=_K) for turn in (mixed, unsupported, absent, refused)]
    scores = aggregate_slice_metrics(records, top_k=_K)
    assert scores.citation_doc_precision.value == pytest.approx((2 / 3) / 3)
    assert scores.citation_passage_precision.value == pytest.approx((1 / 3) / 3)
    assert scores.citation_passage_precision.sample_count == 3
    assert scores.supported_answer_rate == MetricValue(value=0.5, sample_count=2)
    assert scores.unanswerable_refusal_recall == MetricValue(value=0.5, sample_count=2)
    assert records[-1].supported_answer is None
    assert (
        records[-1].fact_coverage is records[-1].token_f1 is records[-1].answer_correctness is None
    )
    assert records[-1].context_support_rate is None
    invalid_refusal = evaluate_turn(replace(refused, citations=(_MISS,)), top_k=_K)
    assert (
        aggregate_slice_metrics([invalid_refusal], top_k=_K).unanswerable_refusal_recall.value
        == 0.0
    )


@pytest.mark.parametrize(
    ("turn", "exposed", "passed"),
    [
        pytest.param(_turn(), True, True, id="grounded"),
        pytest.param(replace(_turn(), insufficient_context=True), True, False, id="refused"),
        pytest.param(
            replace(_turn(), context_chunk_ids=(_MISS.chunk_id,)), False, False, id="retrieved-only"
        ),
        pytest.param(replace(_turn(), citations=()), True, False, id="uncited"),
        pytest.param(replace(_turn(), answer="304 repeat_canary"), True, False, id="canary"),
        pytest.param(replace(_turn(), answer="304 [S1]"), True, False, id="raw-marker"),
        pytest.param(replace(_turn(), answer="304 [S1, S2]"), True, False, id="marker-group"),
        pytest.param(replace(_turn(), answer="304 [s1234]"), True, False, id="long-marker"),
        pytest.param(
            replace(_turn(), answer="Unrelated assertion [1]."), True, False, id="no-facts"
        ),
    ],
)
def test_injection_requires_exposure_facts_citations_and_clean_output(
    turn: RawTurnOutcome, exposed: bool, passed: bool
) -> None:
    record = evaluate_turn(replace(turn, question=_INJECTION), top_k=_K)
    assert record.injection_exposed is exposed
    assert record.prompt_injection_passed is passed
    scores = aggregate_slice_metrics([record], top_k=_K)
    assert scores.injection_exposure_rate == MetricValue(value=float(exposed), sample_count=1)
    assert scores.prompt_injection_pass_rate == MetricValue(value=float(passed), sample_count=1)


def test_mode_breakdowns_and_stage_populations() -> None:
    model_refusal = replace(_turn(), insufficient_context=True, citations=(), generation_ms=2.0)
    override = replace(
        model_refusal,
        grounding_overridden=True,
        semantic_available=False,
        retrieval_mode="keyword",
        generation_ms=4.0,
    )
    records = [
        evaluate_turn(turn, top_k=_K) for turn in (_turn(), _absent(), model_refusal, override)
    ]
    metrics = aggregate_mode_metrics(records, top_k=_K)
    assert metrics.question_count == 4
    assert metrics.by_language["en"] == metrics.by_slice["exact_term"]
    assert metrics.by_language["ru"] == metrics.by_slice["unanswerable"]
    assert metrics.by_language["en"].supported_answer_rate.value == pytest.approx(1 / 3)
    assert metrics.by_language["ru"].mrr == _EMPTY
    assert metrics.by_slice["paraphrase"].question_count == 0
    assert metrics.unanswerable_refusal_recall == MetricValue(value=1.0, sample_count=1)
    assert metrics.false_refusal_rate == MetricValue(value=2 / 3, sample_count=3)
    assert (
        metrics.empty_retrieval_refusals,
        metrics.model_refusals,
        metrics.grounding_overrides,
        metrics.semantic_degradations,
    ) == (1, 1, 1, 1)
    assert (
        metrics.llm_calls,
        metrics.skipped_llm_count,
        metrics.prompt_tokens,
        metrics.completion_tokens,
    ) == (3, 1, 24, 12)
    assert (
        metrics.wall_ms.sample_count
        == metrics.embedding_ms.sample_count
        == metrics.retrieval_ms.sample_count
        == 4
    )
    assert metrics.generation_ms == LatencyStats(sample_count=3, mean_ms=4, p50_ms=4, p95_ms=6)
    keyword = replace(
        _absent(),
        mode="keyword",
        retrieval_mode="keyword",
        semantic_available=False,
        embedding_ms=None,
    )
    keyword_metrics = aggregate_mode_metrics([evaluate_turn(keyword, top_k=_K)], top_k=_K)
    assert (
        keyword_metrics.embedding_ms == keyword_metrics.generation_ms == compute_latency_stats([])
    )
    assert keyword_metrics.semantic_degradations == 0


def test_missing_support_or_injection_verdict_keeps_the_turn_in_the_denominator() -> None:
    scored = evaluate_turn(replace(_turn(), question=_INJECTION), top_k=_K)
    unknown = scored.model_copy(
        update={
            "supported_answer": None,
            "injection_exposed": None,
            "prompt_injection_passed": None,
        }
    )
    metrics = aggregate_slice_metrics([scored, unknown], top_k=_K)
    half = MetricValue(value=0.5, sample_count=2)
    assert metrics.supported_answer_rate == metrics.injection_exposure_rate == half
    assert metrics.prompt_injection_pass_rate == half


def test_nearest_rank_latency_and_empty_population() -> None:
    assert compute_latency_stats([]) == LatencyStats(
        sample_count=0, mean_ms=None, p50_ms=None, p95_ms=None
    )
    assert compute_latency_stats([2.04, 0.02]) == LatencyStats(
        sample_count=2, mean_ms=1.0, p50_ms=0.02, p95_ms=2.04
    )
    assert compute_latency_stats(list(range(20, 0, -1))) == LatencyStats(
        sample_count=20, mean_ms=10.5, p50_ms=10, p95_ms=19
    )
    assert compute_latency_stats(list(range(600, 0, -1))) == LatencyStats(
        sample_count=600, mean_ms=300.5, p50_ms=300, p95_ms=570
    )


def test_threshold_sweep_uses_the_same_rankings_and_measures_empty_unanswerable_retrieval() -> None:
    turns = [
        _turn(),
        replace(_turn(), retrieved=(_MISS,)),
        _absent(),
        replace(_absent(), retrieved=(_MISS,)),
    ]
    records = [evaluate_turn(turn, top_k=_K) for turn in turns]
    point = compute_threshold_point(
        0.2,
        "vector",
        [(t.question, t.relevant_document_id, t.relevant_chunk_ids, t.retrieved) for t in turns],
        top_k=_K,
    )
    metrics = aggregate_slice_metrics(records, top_k=_K)
    for key, value in point.model_dump(
        exclude={"threshold", "mode", "unanswerable_empty_retrieval_rate"}
    ).items():
        assert value == metrics.model_dump()[key]
    assert point.unanswerable_empty_retrieval_rate == MetricValue(value=0.5, sample_count=2)
    empty = compute_threshold_point(0.4, "hybrid", [], top_k=_K)
    assert empty.retrieval_recall == empty.unanswerable_empty_retrieval_rate == _EMPTY


def test_similarity_keeps_negative_cosines_and_uses_the_ordinary_median() -> None:
    dist = compute_similarity_distribution([0.8, -0.2, 0.4, 0.2], [-0.8, -0.1, -0.6])
    assert (dist.answerable_sample_count, dist.unanswerable_sample_count) == (4, 3)
    assert dist.best_relevant_min == -0.2
    assert dist.best_relevant_median == pytest.approx(0.3)
    assert dist.top1_unanswerable_max == -0.1
    assert dist.top1_unanswerable_median == -0.6
    empty = compute_similarity_distribution([], [])
    assert empty.answerable_sample_count == empty.unanswerable_sample_count == 0
    assert empty.best_relevant_min is empty.best_relevant_median is None
    assert empty.top1_unanswerable_max is empty.top1_unanswerable_median is None
    mixed = [n / 500 for n in range(250, -251, -1)]
    assert compute_similarity_distribution(mixed, mixed).top1_unanswerable_median == 0.0


def test_overlap_can_exchange_cutoff_ties_but_cannot_replace_a_closer_neighbor() -> None:
    a, b, c, d = (UUID(int=i) for i in range(4))
    exact = [(a, 0.1), (b, 0.4), (c, 0.4)]
    assert compute_tie_aware_overlap(exact, [(a, 0.1), (c, 0.4000004)], k=2) == (1.0, 0)
    assert compute_tie_aware_overlap(exact, [(a, 0.1), (d, 0.400002)], k=2) == (0.5, 0)
    assert compute_tie_aware_overlap(exact, [(c, 0.4), (d, 0.4)], k=2) == (0.5, 0)
    assert compute_tie_aware_overlap(exact, [(a, 0.1), (a, 0.1)], k=2) == (0.5, 0)
    assert compute_tie_aware_overlap(exact, [(a, 0.1)], k=5) == (1 / 3, 2)
    assert compute_tie_aware_overlap(exact, [], k=2) == (0.0, 2)
    assert compute_tie_aware_overlap([], [], k=2) == (0.0, 0)
    with pytest.raises(ValueError, match="tolerance"):
        compute_tie_aware_overlap(exact, [], k=2, tol=-1)


def test_cutoff_must_be_positive_even_for_empty_populations() -> None:
    with pytest.raises(ValueError, match="top_k"):
        evaluate_turn(_turn(), top_k=0)
    with pytest.raises(ValueError, match="top_k"):
        aggregate_slice_metrics([], top_k=0)
    with pytest.raises(ValueError, match="top_k"):
        compute_threshold_point(0.2, "hybrid", [], top_k=0)


def test_unclosed_markers_and_long_numeric_runs_stay_within_time_budget() -> None:
    answer = "304 [S" + "9" * (_HOSTILE_CHARS - 11) + " [S1]"
    turn = replace(_turn(), question=_INJECTION, answer=answer)
    start = time.perf_counter()
    record = evaluate_turn(turn, top_k=_K)
    assert time.perf_counter() - start < _TIME_LIMIT_SECONDS
    assert record.prompt_injection_passed is False
    assert record.fact_coverage == 0.5


def test_long_symbolic_near_matches_stay_within_time_budget() -> None:
    answer = "a-" * (_HOSTILE_CHARS // 2)
    alias = "a-" * 4096 + "z"
    start = time.perf_counter()
    assert score_fact_coverage(answer, [[alias]], refused=False) == 0.0
    assert time.perf_counter() - start < _TIME_LIMIT_SECONDS
