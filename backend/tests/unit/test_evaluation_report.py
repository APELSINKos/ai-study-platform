from pathlib import Path
from typing import Final
from uuid import UUID

import pytest

from app.schemas.search import SearchMode
from evaluation.metrics import (
    aggregate_mode_metrics,
    compute_similarity_distribution,
    compute_threshold_point,
)
from evaluation.report import (
    DEFAULT_OFFLINE_GATES,
    evaluate_gates,
    render_json,
    render_markdown,
    write_report,
)
from evaluation.schema import (
    EvalPassage,
    EvalProvenance,
    EvalQuestion,
    EvaluationReport,
    HnswArmMetrics,
    HnswDuplicateReport,
    HnswLevelReport,
    MetricValue,
    ModeMetrics,
    QuestionEvalRecord,
    ThresholdSweepReport,
)

_PROVENANCE: Final = EvalProvenance(
    dataset_version="1.2",
    dataset_sha256="ab" * 32,
    live=False,
    llm_model="extractive-v1",
    embedding_model="hashing-v1",
    question_count=4,
    document_count=2,
    chunk_count=6,
    chunk_size_chars=1200,
    chunk_overlap_chars=200,
    candidates_per_list=40,
    rrf_k=60,
    top_k=5,
    min_similarity=0.2,
)
_HIT: Final = EvalPassage(
    chunk_id=UUID(int=1), document_id=UUID(int=2), original_filename="lesson.md", chunk_index=0
)
_MISS: Final = EvalPassage(
    chunk_id=UUID(int=3), document_id=UUID(int=4), original_filename="appendix.md", chunk_index=0
)


def _records() -> list[QuestionEvalRecord]:
    answered = QuestionEvalRecord(
        question_id="cache-validation",
        slice="exact_term",
        language="en",
        mode="hybrid",
        retrieval_mode="hybrid",
        relevant_document="lesson.md",
        relevant_document_id=_HIT.document_id,
        relevant_chunk_ids=[_HIT.chunk_id],
        retrieved=[_HIT],
        context_chunk_ids=[_HIT.chunk_id],
        citations=[_HIT],
        answer="A 304 permits reuse [1].",
        expect_insufficient_context=False,
        insufficient_context=False,
        skipped_llm=False,
        grounding_overridden=False,
        semantic_available=True,
        fact_coverage=1.0,
        token_f1=1.0,
        answer_correctness=1.0,
        context_support_rate=1.0,
        supported_answer=True,
        injection_exposed=None,
        prompt_injection_passed=None,
        wall_ms=11,
        embedding_ms=2,
        retrieval_ms=3,
        generation_ms=5,
        prompt_tokens=12,
        completion_tokens=5,
    )
    translated = answered.model_copy(
        update={"question_id": "cache-rule", "language": "ru", "slice": "paraphrase"}
    )
    injection = answered.model_copy(
        update={
            "question_id": "source-rule",
            "slice": "prompt_injection",
            "injection_exposed": True,
            "prompt_injection_passed": True,
        }
    )
    absent = answered.model_copy(
        update={
            "question_id": "absent-topic",
            "slice": "unanswerable",
            "relevant_document": None,
            "relevant_document_id": None,
            "relevant_chunk_ids": [],
            "retrieved": [],
            "context_chunk_ids": [],
            "citations": [],
            "answer": "Insufficient context.",
            "expect_insufficient_context": True,
            "insufficient_context": True,
            "skipped_llm": True,
            "supported_answer": None,
            "fact_coverage": None,
            "token_f1": None,
            "answer_correctness": None,
            "context_support_rate": None,
            "generation_ms": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
    )
    return [answered, translated, injection, absent]


@pytest.fixture(scope="module")
def report() -> EvaluationReport:
    hybrid = _records()
    records = list(hybrid)
    modes: dict[SearchMode, ModeMetrics] = {
        "hybrid": aggregate_mode_metrics(hybrid, top_k=_PROVENANCE.top_k),
    }
    other_modes: tuple[SearchMode, ...] = ("keyword", "vector")
    for mode in other_modes:
        other = [
            record.model_copy(
                update={
                    "mode": mode,
                    "retrieval_mode": mode,
                    "semantic_available": mode != "keyword",
                    "embedding_ms": 2.0 if mode == "vector" else None,
                }
            )
            for record in hybrid
        ]
        other[0] = other[0].model_copy(
            update={
                "retrieved": [_MISS] if mode == "keyword" else [_MISS, _HIT],
                "supported_answer": False,
            }
        )
        modes[mode] = aggregate_mode_metrics(other, top_k=_PROVENANCE.top_k)
        records.extend(other)
    return EvaluationReport(provenance=_PROVENANCE, modes=modes, records=records)


def _with_hybrid(report: EvaluationReport, hybrid: ModeMetrics) -> EvaluationReport:
    return report.model_copy(update={"modes": {**report.modes, "hybrid": hybrid}})


def _with_rate(report: EvaluationReport, name: str, value: float) -> EvaluationReport:
    return _with_hybrid(
        report,
        report.modes["hybrid"].model_copy(
            update={
                name: MetricValue(value=value, sample_count=100),
            }
        ),
    )


def _live(report: EvaluationReport) -> EvaluationReport:
    return report.model_copy(update={"provenance": _PROVENANCE.model_copy(update={"live": True})})


def test_offline_gates_cover_all_populations_and_both_languages(report: EvaluationReport) -> None:
    checks = evaluate_gates(report)
    assert {check.name for check in checks} == set(DEFAULT_OFFLINE_GATES)
    assert all(check.passed and check.sample_count > 0 for check in checks)
    assert {check.name for check in checks if "by_language" in check.name} == {
        "by_language.en.passage_hit_rate",
        "by_language.ru.passage_hit_rate",
    }
    assert next(c for c in checks if c.name == "semantic_degradations").observed == 0
    for name in ("injection_exposure_rate", "prompt_injection_pass_rate"):
        assert next(c for c in checks if c.name == name).threshold == 1


def test_always_refusing_fails_answer_and_injection_gates(report: EvaluationReport) -> None:
    records = [
        r.model_copy(
            update={
                "insufficient_context": True,
                "citations": [],
                "supported_answer": False,
                "prompt_injection_passed": False if r.slice == "prompt_injection" else None,
            }
        )
        for r in _records()
    ]
    refusing = _with_hybrid(report, aggregate_mode_metrics(records, top_k=_PROVENANCE.top_k))
    failed = {c.name for c in evaluate_gates(refusing) if not c.passed}
    assert {"supported_answer_rate", "false_refusal_rate", "prompt_injection_pass_rate"} <= failed
    assert "unanswerable_refusal_recall" not in failed


def test_language_floor_catches_a_regression_hidden_by_the_overall_score(
    report: EvaluationReport,
) -> None:
    hybrid = report.modes["hybrid"]
    russian = hybrid.by_language["ru"].model_copy(
        update={"passage_hit_rate": MetricValue(value=0.4, sample_count=5)}
    )
    current = _with_hybrid(
        report, hybrid.model_copy(update={"by_language": {**hybrid.by_language, "ru": russian}})
    )
    failed = {c.name for c in evaluate_gates(current, baseline=report) if not c.passed}
    assert failed == {"by_language.ru.passage_hit_rate", "baseline.by_language.ru.passage_hit_rate"}


def test_missing_hybrid_or_gate_population_fails(report: EvaluationReport) -> None:
    missing = report.model_copy(update={"modes": {"keyword": report.modes["keyword"]}})
    [missing_gate] = evaluate_gates(missing)
    assert not missing_gate.passed
    assert missing_gate.observed is None
    assert missing_gate.sample_count == 0
    checks = evaluate_gates(report, baseline=missing)
    assert any(not c.passed and c.name == "baseline.hybrid_present" for c in checks)
    partial = aggregate_mode_metrics(_records()[:1], top_k=_PROVENANCE.top_k)
    partial_checks = {c.name: c for c in evaluate_gates(_with_hybrid(report, partial))}
    for name in (
        "by_language.ru.passage_hit_rate",
        "injection_exposure_rate",
        "unanswerable_refusal_recall",
    ):
        assert partial_checks[name].observed is None
        assert partial_checks[name].sample_count == 0
        assert not partial_checks[name].passed
    missing_language = _with_hybrid(report, partial.model_copy(update={"by_language": {}}))
    assert any(
        not c.passed and "by_language.en" in c.name for c in evaluate_gates(missing_language)
    )
    assert any(
        not c.passed and "population" in c.name
        for c in evaluate_gates(report, baseline=missing_language)
    )


def test_live_runs_require_a_baseline_and_skip_absolute_offline_floors(
    report: EvaluationReport,
) -> None:
    live = _live(_with_rate(report, "mrr", 0.1))
    with pytest.raises(
        ValueError,
        match=r"^Offline gates do not apply to --live runs; "
        r"pass --baseline to compare against a saved live baseline\.$",
    ):
        evaluate_gates(live)
    checks = evaluate_gates(live, baseline=live)
    assert all(c.name.startswith("baseline.") and c.passed for c in checks)


@pytest.mark.parametrize(
    ("observed", "passes"), [(0.85, False), (0.87, True), (0.88, True), (1.0, True)]
)
def test_baseline_floor_allows_at_most_three_points(
    report: EvaluationReport, observed: float, passes: bool
) -> None:
    baseline = _with_rate(report, "mrr", 0.90)
    checks = evaluate_gates(_with_rate(report, "mrr", observed), baseline=baseline)
    gate = next(c for c in checks if c.name == "baseline.mrr")
    assert gate.passed is passes
    assert gate.threshold == pytest.approx(0.87)
    assert gate.observed == observed


def test_false_refusal_has_a_ceiling_and_delta_can_be_configured(report: EvaluationReport) -> None:
    baseline = _with_rate(report, "false_refusal_rate", 0.2)
    worse = _with_rate(report, "false_refusal_rate", 0.24)
    gate = next(
        c
        for c in evaluate_gates(worse, baseline=baseline)
        if c.name == "baseline.false_refusal_rate"
    )
    assert gate.threshold == pytest.approx(0.23)
    assert not gate.passed
    assert all(
        c.passed for c in evaluate_gates(worse, baseline=baseline, max_regression_delta=0.04)
    )
    with pytest.raises(ValueError, match="nonnegative"):
        evaluate_gates(report, baseline=baseline, max_regression_delta=-0.1)


@pytest.mark.parametrize("name", ["prompt_injection_pass_rate", "injection_exposure_rate"])
def test_injection_baselines_allow_zero_drop(report: EvaluationReport, name: str) -> None:
    live = _live(report)
    current = _with_rate(live, name, 0.999999)
    gate = next(c for c in evaluate_gates(current, baseline=live) if c.name == f"baseline.{name}")
    assert not gate.passed
    assert gate.threshold == 1.0


def test_semantic_degradation_must_be_zero_even_against_a_degraded_baseline(
    report: EvaluationReport,
) -> None:
    degraded = _live(
        _with_hybrid(report, report.modes["hybrid"].model_copy(update={"semantic_degradations": 2}))
    )
    gate = next(
        c
        for c in evaluate_gates(degraded, baseline=degraded)
        if c.name == "baseline.semantic_degradations"
    )
    assert not gate.passed
    assert gate.observed == 2
    assert gate.threshold == 0


def _diagnostics(report: EvaluationReport) -> EvaluationReport:
    rate = MetricValue(value=1, sample_count=3)
    exact = HnswArmMetrics(
        plan_verified=True,
        exact_topk_overlap=rate,
        missing_rows=0,
        passage_recall=rate,
        doc_hit_rate=rate,
    )
    limited = exact.model_copy(
        update={
            "plan_verified": False,
            "missing_rows": 2,
            "exact_topk_overlap": MetricValue(value=0.6, sample_count=3),
        }
    )
    level = HnswLevelReport(
        decoy_workspaces=8, exact=exact, hnsw_no_iterative=limited, hnsw_iterative=exact
    )
    probe = HnswDuplicateReport(
        levels=[level, level.model_copy(update={"decoy_workspaces": 40})],
        distinct_vector_control=level.model_copy(update={"decoy_workspaces": 64}),
    )
    question = EvalQuestion(
        id="cache",
        slice="exact_term",
        language="en",
        question="Which code?",
        expected_answer="304",
        relevant_document="lesson.md",
        relevant_headings=["Cache"],
        expected_facts=[["304"]],
    )
    point = compute_threshold_point(
        0.2, "hybrid", [(question, _HIT.document_id, [_HIT.chunk_id], [_HIT])], top_k=5
    )
    sweep = ThresholdSweepReport(
        points=[point], similarity=compute_similarity_distribution([-0.2, 0.6], [0.1])
    )
    return report.model_copy(
        update={
            "threshold_sweep": sweep,
            "hnsw_duplicate_probe": probe,
            "gates": evaluate_gates(report),
        }
    )


def test_detailed_report_round_trips_and_renders_counts_comparisons_and_controls(
    report: EvaluationReport,
) -> None:
    detailed = _diagnostics(report)
    raw = render_json(detailed)
    assert raw == detailed.model_dump_json(indent=2) + "\n"
    assert EvaluationReport.model_validate_json(raw) == detailed
    output = render_markdown(detailed)
    for text in (
        "## Provenance",
        "Offline",
        "extractive-v1",
        "hashing-v1",
        _PROVENANCE.dataset_sha256,
        "1200 / 200",
        "min_similarity",
        "## Mode comparison",
        "| Metric | vector | keyword | hybrid |",
        "Doc Hit@k",
        "Doc MRR",
        "Passage Hit@k",
        "P@k",
        "AP@k",
        "Recall@k",
        "MRR",
        "Chunk Precision",
        "Fact Coverage",
        "Token F1",
        "Correctness",
        "Context Support",
        "Supported Answer",
        "Citation Passage Precision",
        "Unanswerable Refusal Recall",
        "False Refusal",
        "Injection Pass",
        "Wall p50 / p95 (ms)",
        "## Hybrid by slice",
        "## Hybrid by language",
        "## Paired mode differences",
        "cache-validation (miss to rank 1",
        "cache-validation (rank 2 to rank 1",
        "## Refusal and telemetry summary",
        "Grounding overrides",
        "Semantic degradations",
        "Prompt tokens",
        "Completion tokens",
        "| keyword | Embedding | 0 |",
        "| hybrid | Generation | 3 |",
        "## Threshold calibration sweep",
        "### Similarity distribution",
        "| Best relevant | 2 | -0.200 | 0.200 |",
        "## HNSW duplicate-vector diagnostic",
        "| Duplicate vectors | 40 | HNSW, iterative off | no | 0.600 (n=3) | 2 |",
        "| Distinct-vector control | 64 |",
        "Plan verified",
        "Passage recall",
        "## Regression gates",
        "| false_refusal_rate | 0.000 | <= 0.250 | 3 | Pass |",
        "## Caveats",
        "regression signal",
        "extractive",
        "Live generative",
        "injection",
    ):
        assert text in output, text
    assert output.endswith("\n")
    assert render_markdown(detailed) == output


def test_markdown_uses_public_metadata_and_omits_unsupplied_sections(
    report: EvaluationReport,
) -> None:
    annotated = report.model_copy(
        update={
            "provenance": _PROVENANCE.model_copy(
                update={
                    "llm_model": "private/model/location",
                    "embedding_model": "private?display=off",
                }
            ),
            "records": [
                r.model_copy(update={"answer": "unpublished payload"}) for r in report.records
            ],
        }
    )
    output = render_markdown(annotated)
    for term in (
        "private",
        "unpublished",
        "://",
        _HIT.original_filename,
        "## Threshold",
        "## HNSW",
        "## Regression gates",
    ):
        assert term not in output
    assert "(withheld)" in output
    assert _PROVENANCE.dataset_sha256 in output


def test_write_report_creates_utf8_lf_files_in_the_output_directory(
    report: EvaluationReport, tmp_path: Path
) -> None:
    detailed = _diagnostics(report)
    destination = tmp_path / "reports"
    json_path, markdown_path = write_report(detailed, destination, "trial")
    assert (json_path, markdown_path) == (destination / "trial.json", destination / "trial.md")
    for path, expected in (
        (json_path, render_json(detailed)),
        (markdown_path, render_markdown(detailed)),
    ):
        data = path.read_bytes()
        assert data == expected.encode("utf-8")
        assert data.endswith(b"\n")
        assert b"\r" not in data
    assert EvaluationReport.model_validate_json(json_path.read_bytes()) == detailed
    assert write_report(report, destination, "trial") == (json_path, markdown_path)
    assert EvaluationReport.model_validate_json(json_path.read_bytes()) == report


@pytest.mark.parametrize("prefix", ["", "..", "../outside", r"..\outside"])
def test_report_prefix_must_stay_in_the_output_directory(
    report: EvaluationReport, tmp_path: Path, prefix: str
) -> None:
    with pytest.raises(ValueError, match="filename stem"):
        write_report(report, tmp_path, prefix)
