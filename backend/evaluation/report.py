"""Regression checks and portable reports for a completed evaluation."""

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from typing import Final

from app.schemas.search import SearchMode
from evaluation.metrics import METRIC_VERSION, rank_passages
from evaluation.schema import (
    EvalLanguage,
    EvalProvenance,
    EvaluationReport,
    GateCheckResult,
    HnswDuplicateReport,
    MetricValue,
    ModeMetrics,
    QuestionEvalRecord,
    SliceMetrics,
    ThresholdSweepReport,
)

_MODE_ORDER: Final[tuple[SearchMode, ...]] = ("vector", "keyword", "hybrid")
_PAIRED_MODES: Final[tuple[SearchMode, ...]] = ("keyword", "vector")
_LANGUAGE_GATES: Final[dict[str, EvalLanguage]] = {
    "by_language.en.passage_hit_rate": "en",
    "by_language.ru.passage_hit_rate": "ru",
}
_CEILINGS: Final = frozenset({"false_refusal_rate", "semantic_degradations"})
_NO_DROP: Final = frozenset({"injection_exposure_rate", "prompt_injection_pass_rate"})
DEFAULT_OFFLINE_GATES: Final = {
    "doc_hit_rate": 0.80,
    "passage_hit_rate": 0.70,
    "retrieval_recall": 0.50,
    "mrr": 0.55,
    "context_precision": 0.55,
    "supported_answer_rate": 0.50,
    "false_refusal_rate": 0.25,
    "unanswerable_refusal_recall": 0.50,
    "injection_exposure_rate": 1.0,
    "prompt_injection_pass_rate": 1.0,
    "semantic_degradations": 0.0,
    "by_language.en.passage_hit_rate": 0.65,
    "by_language.ru.passage_hit_rate": 0.65,
}
_RATE_LABELS: Final = {
    "doc_hit_rate": "Doc Hit@k",
    "doc_mrr": "Doc MRR",
    "passage_hit_rate": "Passage Hit@k",
    "precision_at_k": "P@k",
    "context_precision": "AP@k",
    "retrieval_recall": "Recall@k",
    "mrr": "MRR",
    "chunk_precision": "Chunk Precision",
    "fact_coverage": "Fact Coverage",
    "token_f1": "Token F1",
    "answer_correctness": "Correctness",
    "context_support_rate": "Context Support",
    "supported_answer_rate": "Supported Answer",
    "citation_doc_precision": "Citation Doc Precision",
    "citation_passage_precision": "Citation Passage Precision",
    "unanswerable_refusal_recall": "Unanswerable Refusal Recall",
    "false_refusal_rate": "False Refusal",
    "injection_exposure_rate": "Injection Exposure",
    "prompt_injection_pass_rate": "Injection Pass",
}
_BREAKDOWN_RATES: Final = (
    "passage_hit_rate",
    "retrieval_recall",
    "mrr",
    "answer_correctness",
    "supported_answer_rate",
    "false_refusal_rate",
    "unanswerable_refusal_recall",
    "prompt_injection_pass_rate",
)
_EXAMPLE_LIMIT: Final = 3
_PUBLIC_LABEL: Final = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._+-]*+")


def _rate(metrics: SliceMetrics, name: str) -> MetricValue:
    rate = getattr(metrics, name)
    if not isinstance(rate, MetricValue):
        raise TypeError(f"{name} is not a rate.")
    return rate


def _observation(metrics: ModeMetrics, name: str) -> tuple[float | None, int]:
    if name == "semantic_degradations":
        return (
            float(metrics.semantic_degradations) if metrics.question_count else None,
            metrics.question_count,
        )
    if name in _LANGUAGE_GATES:
        group = metrics.by_language.get(_LANGUAGE_GATES[name])
        if group is None:
            return None, 0
        rate = group.passage_hit_rate
    else:
        rate = _rate(metrics, name)
    return rate.value, rate.sample_count


def _check(
    name: str, observation: tuple[float | None, int], threshold: float, *, ceiling: bool = False
) -> GateCheckResult:
    value, count = observation
    return GateCheckResult(
        name=name,
        observed=value,
        threshold=threshold,
        sample_count=count,
        passed=count > 0
        and value is not None
        and (value <= threshold if ceiling else value >= threshold),
    )


def evaluate_gates(
    report: EvaluationReport,
    *,
    baseline: EvaluationReport | None = None,
    max_regression_delta: float = 0.03,
) -> list[GateCheckResult]:
    if report.provenance.live and baseline is None:
        raise ValueError(
            "Offline gates do not apply to --live runs; "
            "pass --baseline to compare against a saved live baseline."
        )
    if not math.isfinite(max_regression_delta) or max_regression_delta < 0:
        raise ValueError("max_regression_delta must be finite and nonnegative.")
    hybrid = report.modes.get("hybrid")
    if hybrid is None:
        return [_check("hybrid_present", (None, 0), 1.0)]
    checks: list[GateCheckResult] = []
    if not report.provenance.live:
        checks.extend(
            _check(name, _observation(hybrid, name), threshold, ceiling=name in _CEILINGS)
            for name, threshold in DEFAULT_OFFLINE_GATES.items()
        )
    if baseline is None:
        return checks
    reference = baseline.modes.get("hybrid")
    if reference is None:
        return [*checks, _check("baseline.hybrid_present", (None, 0), 1.0)]
    delta = Decimal(str(max_regression_delta))
    for name in DEFAULT_OFFLINE_GATES:
        gate_name = f"baseline.{name}"
        previous, count = _observation(reference, name)
        if previous is None or count == 0:
            checks.append(_check(f"{gate_name}.population", (None, 0), 1.0))
            continue
        ceiling = name in _CEILINGS
        if name == "semantic_degradations":
            threshold = 0.0
        elif name in _NO_DROP:
            threshold = previous
        else:
            threshold = float(Decimal(str(previous)) + (delta if ceiling else -delta))
        checks.append(_check(gate_name, _observation(hybrid, name), threshold, ceiling=ceiling))
    return checks


def render_json(report: EvaluationReport) -> str:
    return report.model_dump_json(indent=2) + "\n"


def _label(value: str) -> str:
    # Only display public identifiers in Markdown, even when rendering an imported report.
    if _PUBLIC_LABEL.fullmatch(value) and not value.lower().startswith("sk-"):
        return value
    return "(withheld)"


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    def row(cells: Sequence[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    return "\n".join((row(headers), row(["---"] * len(headers)), *(row(cells) for cells in rows)))


def _value(value: float | None, digits: int = 3) -> str:
    return "\u2014" if value is None else f"{value:.{digits}f}"


def _measurement(metric: MetricValue) -> str:
    return f"{_value(metric.value)} (n={metric.sample_count})"


def _provenance(p: EvalProvenance) -> str:
    return _table(
        ("Setting", "Value"),
        (
            ("Run", "Live" if p.live else "Offline"),
            ("LLM model", _label(p.llm_model)),
            ("Embedding model", _label(p.embedding_model)),
            ("Dataset version", _label(p.dataset_version)),
            ("Dataset SHA-256", p.dataset_sha256),
            ("Metric version", METRIC_VERSION),
            (
                "Questions / documents / chunks",
                f"{p.question_count} / {p.document_count} / {p.chunk_count}",
            ),
            (
                "Chunk size / overlap (characters)",
                f"{p.chunk_size_chars} / {p.chunk_overlap_chars}",
            ),
            ("Candidates per list / RRF k", f"{p.candidates_per_list} / {p.rrf_k}"),
            ("Top k", str(p.top_k)),
            ("min_similarity", str(p.min_similarity)),
        ),
    )


def _mode_comparison(modes: Mapping[SearchMode, ModeMetrics]) -> str:
    rows = [
        [label, *(_measurement(_rate(metrics, name)) for metrics in modes.values())]
        for name, label in _RATE_LABELS.items()
    ]
    rows.append(
        [
            "Wall p50 / p95 (ms)",
            *(
                f"{_value(m.wall_ms.p50_ms, 1)} / {_value(m.wall_ms.p95_ms, 1)} "
                f"(n={m.wall_ms.sample_count})"
                for m in modes.values()
            ),
        ]
    )
    return _table(["Metric", *modes], rows)


def _breakdown[K: str](groups: Mapping[K, SliceMetrics], title: str) -> str:
    return _table(
        [title, "Questions", *(_RATE_LABELS[key] for key in _BREAKDOWN_RATES)],
        (
            [
                name,
                str(metrics.question_count),
                *(_measurement(_rate(metrics, key)) for key in _BREAKDOWN_RATES),
            ]
            for name, metrics in groups.items()
        ),
    )


def _passage_rank(record: QuestionEvalRecord, top_k: int) -> int | None:
    return rank_passages(
        record.relevant_document_id, record.relevant_chunk_ids, record.retrieved, top_k=top_k
    ).passage_rank


def _paired_differences(report: EvaluationReport) -> str:
    records = {
        (r.mode, r.question_id): r for r in report.records if not r.expect_insufficient_context
    }
    top_k = report.provenance.top_k
    rows = []
    for mode in _PAIRED_MODES:
        if mode not in report.modes:
            continue
        paired = earlier = later = gained = lost = 0
        examples: list[str] = []
        for (current, question_id), hybrid in records.items():
            if current != "hybrid" or (other := records.get((mode, question_id))) is None:
                continue
            left, right = _passage_rank(hybrid, top_k), _passage_rank(other, top_k)
            rank_gain = (left or top_k + 1) < (right or top_k + 1)
            support_gain = bool(hybrid.supported_answer and not other.supported_answer)
            paired += 1
            earlier += rank_gain
            later += (left or top_k + 1) > (right or top_k + 1)
            gained += support_gain
            lost += bool(other.supported_answer and not hybrid.supported_answer)
            if (rank_gain or support_gain) and len(examples) < _EXAMPLE_LIMIT:
                differences = []
                if rank_gain:
                    previous = f"rank {right}" if right is not None else "miss"
                    differences.append(f"{previous} to rank {left}")
                if support_gain:
                    differences.append("gained a supported answer")
                examples.append(f"{_label(question_id)} ({', '.join(differences)})")
        rows.append(
            [
                mode,
                str(paired),
                f"{earlier} / {paired - earlier - later} / {later}",
                f"{gained} / {lost}",
                ", ".join(examples) or "\u2014",
            ]
        )
    return _table(
        (
            "Compared with",
            "Paired questions",
            "First relevant passage rank, hybrid earlier / tied / later",
            "Supported answers gained / lost",
            "Examples of hybrid gains",
        ),
        rows,
    )


def _telemetry(modes: Mapping[SearchMode, ModeMetrics]) -> str:
    counts = _table(
        (
            "Mode",
            "Empty retrieval refusals",
            "Model refusals",
            "Grounding overrides",
            "Semantic degradations",
            "LLM calls",
            "Skipped LLM",
            "Prompt tokens",
            "Completion tokens",
        ),
        (
            [
                name,
                *(
                    str(n)
                    for n in (
                        m.empty_retrieval_refusals,
                        m.model_refusals,
                        m.grounding_overrides,
                        m.semantic_degradations,
                        m.llm_calls,
                        m.skipped_llm_count,
                        m.prompt_tokens,
                        m.completion_tokens,
                    )
                ),
            ]
            for name, m in modes.items()
        ),
    )
    stages = _table(
        ("Mode", "Stage", "n", "Mean ms", "p50 ms", "p95 ms"),
        (
            (
                name,
                stage,
                str(stats.sample_count),
                _value(stats.mean_ms, 1),
                _value(stats.p50_ms, 1),
                _value(stats.p95_ms, 1),
            )
            for name, m in modes.items()
            for stage, stats in (
                ("Wall", m.wall_ms),
                ("Embedding", m.embedding_ms),
                ("Retrieval", m.retrieval_ms),
                ("Generation", m.generation_ms),
            )
        ),
    )
    return f"{counts}\n\n{stages}"


def _threshold_sweep(sweep: ThresholdSweepReport) -> str:
    points = _table(
        (
            "Mode",
            "Threshold",
            "Doc Hit@k",
            "Doc MRR",
            "Passage Hit@k",
            "P@k",
            "Chunk Precision",
            "AP@k",
            "Recall@k",
            "MRR",
            "Unanswerable empty retrieval",
        ),
        (
            [
                point.mode,
                str(point.threshold),
                *(
                    _measurement(rate)
                    for rate in (
                        point.doc_hit_rate,
                        point.doc_mrr,
                        point.passage_hit_rate,
                        point.precision_at_k,
                        point.chunk_precision,
                        point.context_precision,
                        point.retrieval_recall,
                        point.mrr,
                        point.unanswerable_empty_retrieval_rate,
                    )
                ),
            ]
            for point in sweep.points
        ),
    )
    s = sweep.similarity
    distribution = _table(
        ("Cosine before filtering", "n", "Minimum", "Median", "Maximum"),
        (
            (
                "Best relevant",
                str(s.answerable_sample_count),
                _value(s.best_relevant_min),
                _value(s.best_relevant_median),
                "\u2014",
            ),
            (
                "Top-1 unanswerable",
                str(s.unanswerable_sample_count),
                "\u2014",
                _value(s.top1_unanswerable_median),
                _value(s.top1_unanswerable_max),
            ),
        ),
    )
    return f"{points}\n\n### Similarity distribution\n\n{distribution}"


def _hnsw_probe(probe: HnswDuplicateReport) -> str:
    levels = [("Duplicate vectors", level) for level in probe.levels]
    levels.append(("Distinct-vector control", probe.distinct_vector_control))
    return _table(
        (
            "Vectors",
            "Decoy workspaces",
            "Arm",
            "Plan verified",
            "Exact top-k overlap",
            "Missing rows",
            "Passage recall",
            "Doc hit",
        ),
        (
            (
                vectors,
                str(level.decoy_workspaces),
                arm,
                "yes" if result.plan_verified else "no",
                _measurement(result.exact_topk_overlap),
                str(result.missing_rows),
                _measurement(result.passage_recall),
                _measurement(result.doc_hit_rate),
            )
            for vectors, level in levels
            for arm, result in (
                ("Exact", level.exact),
                ("HNSW, iterative off", level.hnsw_no_iterative),
                ("HNSW, iterative on", level.hnsw_iterative),
            )
        ),
    )


def _gates_table(gates: Sequence[GateCheckResult]) -> str:
    return _table(
        ("Gate (hybrid)", "Observed", "Requirement", "n", "Result"),
        (
            (
                _label(g.name),
                _value(g.observed),
                f"{'<=' if g.name.removeprefix('baseline.') in _CEILINGS else '>='} "
                f"{g.threshold:.3f}",
                str(g.sample_count),
                "Pass" if g.passed else "Fail",
            )
            for g in gates
        ),
    )


def render_markdown(report: EvaluationReport) -> str:
    modes = {name: report.modes[name] for name in _MODE_ORDER if name in report.modes}
    sections = [
        "# Retrieval evaluation",
        "## Provenance",
        _provenance(report.provenance),
        "## Mode comparison",
        _mode_comparison(modes),
    ]
    if hybrid := modes.get("hybrid"):
        sections.extend(
            (
                "## Hybrid by slice",
                _breakdown(hybrid.by_slice, "Slice"),
                "## Hybrid by language",
                _breakdown(hybrid.by_language, "Language"),
                "## Paired mode differences",
                _paired_differences(report),
            )
        )
    sections.extend(("## Refusal and telemetry summary", _telemetry(modes)))
    if report.threshold_sweep is not None:
        sections.extend(
            ("## Threshold calibration sweep", _threshold_sweep(report.threshold_sweep))
        )
    if report.hnsw_duplicate_probe is not None:
        sections.extend(
            ("## HNSW duplicate-vector diagnostic", _hnsw_probe(report.hnsw_duplicate_probe))
        )
    if report.gates:
        sections.extend(("## Regression gates", _gates_table(report.gates)))
    sections.extend(
        (
            "## Caveats",
            "The small corpus provides a regression signal. Offline answers are extractive. "
            "Live generative answers can express the same facts with different wording. "
            "Offline injection results measure only pipeline and extractive hygiene.",
        )
    )
    return "\n\n".join(sections) + "\n"


def write_report(report: EvaluationReport, output_dir: Path, prefix: str) -> tuple[Path, Path]:
    if not prefix or prefix in {".", ".."} or PureWindowsPath(prefix).name != prefix:
        raise ValueError("prefix must be a filename stem.")
    json_text, markdown = render_json(report), render_markdown(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, markdown_path = output_dir / f"{prefix}.json", output_dir / f"{prefix}.md"
    json_path.write_text(json_text, encoding="utf-8", newline="\n")
    markdown_path.write_text(markdown, encoding="utf-8", newline="\n")
    return json_path, markdown_path
