"""Dataset, provenance and report contracts for a reproducible retrieval evaluation."""

from hashlib import sha256
from pathlib import Path
from typing import Annotated, Final, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.search import SearchMode

DEFAULT_DATASET_DIR: Final = Path(__file__).resolve().parent / "dataset"

type EvalSlice = Literal[
    "exact_term", "paraphrase", "heading_synthesis", "follow_up", "unanswerable", "prompt_injection"
]
type EvalLanguage = Literal["en", "ru"]
type _Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type _FactAliases = Annotated[list[_Text], Field(min_length=1)]
type _Rate = Annotated[float, Field(ge=0, le=1)]
type _Cosine = Annotated[float, Field(ge=-1, le=1)]


class _EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class EvalHistoryTurn(_EvalModel):
    role: Literal["user", "assistant"]
    content: _Text


class EvalQuestion(_EvalModel):
    id: Annotated[_Text, Field(pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")]
    slice: EvalSlice
    language: EvalLanguage
    question: _Text
    history: list[EvalHistoryTurn] = Field(default_factory=list)
    expected_answer: Annotated[str, StringConstraints(strip_whitespace=True)]
    relevant_document: _Text | None
    relevant_headings: list[_Text] = Field(default_factory=list)
    relevant_phrases: list[_Text] = Field(default_factory=list)
    expected_facts: list[_FactAliases] = Field(default_factory=list)
    forbidden_strings: list[_Text] = Field(default_factory=list)
    expect_insufficient_context: bool = False
    fact_group: _Text | None = None

    @field_validator(
        "expected_facts", mode="before", json_schema_input_type=list[_Text | _FactAliases]
    )
    @classmethod
    def _normalize_facts(cls, value: object) -> object:
        if isinstance(value, list):
            return [[item] if isinstance(item, str) else item for item in value]
        return value

    @model_validator(mode="after")
    def _check_reference(self) -> Self:
        if self.slice == "unanswerable" and not self.expect_insufficient_context:
            raise ValueError("The unanswerable slice requires insufficient context.")
        if self.slice == "prompt_injection" and (
            self.expect_insufficient_context or not self.forbidden_strings
        ):
            raise ValueError("Prompt injection requires an answer and forbidden strings.")
        if self.expect_insufficient_context:
            if self.relevant_document is not None or (
                self.relevant_headings or self.relevant_phrases or self.expected_facts
            ):
                raise ValueError(
                    "An unanswerable question cannot have a document, anchors or facts."
                )
        elif not (
            self.expected_answer
            and self.relevant_document is not None
            and (self.relevant_headings or self.relevant_phrases)
            and self.expected_facts
        ):
            raise ValueError(
                "An answerable question requires an answer, document, anchors and facts."
            )
        return self


class EvalDataset(_EvalModel):
    version: _Text
    questions: Annotated[list[EvalQuestion], Field(min_length=1)]

    @model_validator(mode="after")
    def _check_ids(self) -> Self:
        ids = {question.id for question in self.questions}
        if len(ids) != len(self.questions):
            raise ValueError("Duplicate question id in dataset.")
        return self


def load_dataset(
    dataset_dir: Path = DEFAULT_DATASET_DIR,
) -> tuple[EvalDataset, dict[str, Path], str]:
    """Hash each relative UTF-8 filename, a NUL, and the digest of its LF-normalized content."""
    digest = sha256()

    def read_file(path: Path) -> bytes:
        content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(path.relative_to(dataset_dir).as_posix().encode("utf-8") + b"\0")
        digest.update(sha256(content).digest())
        return content

    dataset = EvalDataset.model_validate_json(read_file(dataset_dir / "questions.json"))
    paths = sorted((dataset_dir / "corpus").iterdir(), key=lambda path: path.name)
    corpus = {path.name: path for path in paths if path.is_file()}
    for question in dataset.questions:
        if question.relevant_document is not None and question.relevant_document not in corpus:
            raise ValueError(
                f"{question.id} refers to missing corpus file {question.relevant_document!r}"
            )
    for path in corpus.values():
        read_file(path)
    return dataset, corpus, digest.hexdigest()


class EvalProvenance(_EvalModel):
    dataset_version: _Text
    dataset_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    live: bool
    llm_model: _Text
    embedding_model: _Text
    question_count: PositiveInt
    document_count: PositiveInt
    chunk_count: PositiveInt
    chunk_size_chars: PositiveInt
    chunk_overlap_chars: NonNegativeInt
    candidates_per_list: PositiveInt
    rrf_k: PositiveInt
    top_k: PositiveInt
    min_similarity: _Rate


class MetricValue(_EvalModel):
    """A rate or mean with its actual denominator, including empty populations."""

    value: _Rate | None
    sample_count: NonNegativeInt

    @model_validator(mode="after")
    def _check_population(self) -> Self:
        if (self.sample_count == 0) != (self.value is None):
            raise ValueError("A metric is null exactly when its sample count is zero.")
        return self


class LatencyStats(_EvalModel):
    sample_count: NonNegativeInt
    mean_ms: NonNegativeFloat | None
    p50_ms: NonNegativeFloat | None
    p95_ms: NonNegativeFloat | None

    @model_validator(mode="after")
    def _check_population(self) -> Self:
        for value in (self.mean_ms, self.p50_ms, self.p95_ms):
            if (self.sample_count == 0) != (value is None):
                raise ValueError("Latency statistics are null exactly when no stage was attempted.")
        return self


class _RetrievalMetrics(_EvalModel):
    doc_hit_rate: MetricValue
    doc_mrr: MetricValue
    passage_hit_rate: MetricValue
    precision_at_k: MetricValue
    chunk_precision: MetricValue
    context_precision: MetricValue
    retrieval_recall: MetricValue
    mrr: MetricValue


class SliceMetrics(_RetrievalMetrics):
    question_count: NonNegativeInt
    fact_coverage: MetricValue
    token_f1: MetricValue
    answer_correctness: MetricValue
    context_support_rate: MetricValue
    supported_answer_rate: MetricValue
    citation_doc_precision: MetricValue
    citation_passage_precision: MetricValue
    unanswerable_refusal_recall: MetricValue
    false_refusal_rate: MetricValue
    injection_exposure_rate: MetricValue
    prompt_injection_pass_rate: MetricValue


class ModeMetrics(SliceMetrics):
    by_slice: dict[EvalSlice, SliceMetrics]
    by_language: dict[EvalLanguage, SliceMetrics]
    empty_retrieval_refusals: NonNegativeInt
    model_refusals: NonNegativeInt
    grounding_overrides: NonNegativeInt
    semantic_degradations: NonNegativeInt
    llm_calls: NonNegativeInt
    skipped_llm_count: NonNegativeInt
    prompt_tokens: NonNegativeInt
    completion_tokens: NonNegativeInt
    wall_ms: LatencyStats
    embedding_ms: LatencyStats
    retrieval_ms: LatencyStats
    generation_ms: LatencyStats


class EvalPassage(_EvalModel):
    document_id: UUID
    chunk_id: UUID
    original_filename: _Text
    chunk_index: NonNegativeInt


class QuestionEvalRecord(_EvalModel):
    question_id: _Text
    slice: EvalSlice
    language: EvalLanguage
    mode: SearchMode
    retrieval_mode: SearchMode
    relevant_document: _Text | None
    relevant_document_id: UUID | None
    relevant_chunk_ids: list[UUID]
    retrieved: list[EvalPassage]
    context_chunk_ids: list[UUID]
    citations: list[EvalPassage]
    answer: str
    expect_insufficient_context: bool
    insufficient_context: bool
    skipped_llm: bool
    grounding_overridden: bool
    semantic_available: bool
    fact_coverage: _Rate | None
    token_f1: _Rate | None
    answer_correctness: _Rate | None
    context_support_rate: _Rate | None
    supported_answer: bool | None
    injection_exposed: bool | None
    prompt_injection_passed: bool | None
    wall_ms: NonNegativeFloat
    embedding_ms: NonNegativeFloat | None
    retrieval_ms: NonNegativeFloat
    generation_ms: NonNegativeFloat | None
    prompt_tokens: NonNegativeInt
    completion_tokens: NonNegativeInt


class ThresholdPoint(_RetrievalMetrics):
    threshold: _Rate
    mode: Literal["vector", "hybrid"]
    unanswerable_empty_retrieval_rate: MetricValue


class SimilarityDistribution(_EvalModel):
    """Cosines of the best eligible chunk per question before threshold filtering."""

    answerable_sample_count: NonNegativeInt
    best_relevant_min: _Cosine | None
    best_relevant_median: _Cosine | None
    unanswerable_sample_count: NonNegativeInt
    top1_unanswerable_max: _Cosine | None
    top1_unanswerable_median: _Cosine | None

    @model_validator(mode="after")
    def _check_populations(self) -> Self:
        for count, values in (
            (self.answerable_sample_count, (self.best_relevant_min, self.best_relevant_median)),
            (
                self.unanswerable_sample_count,
                (self.top1_unanswerable_max, self.top1_unanswerable_median),
            ),
        ):
            if any((count == 0) != (value is None) for value in values):
                raise ValueError("Similarity statistics require their corresponding population.")
        return self


class ThresholdSweepReport(_EvalModel):
    similarity: SimilarityDistribution
    points: list[ThresholdPoint]


class HnswArmMetrics(_EvalModel):
    plan_verified: bool
    exact_topk_overlap: MetricValue
    missing_rows: NonNegativeInt
    passage_recall: MetricValue
    doc_hit_rate: MetricValue


class HnswLevelReport(_EvalModel):
    decoy_workspaces: PositiveInt
    exact: HnswArmMetrics
    hnsw_no_iterative: HnswArmMetrics
    hnsw_iterative: HnswArmMetrics


class HnswDuplicateReport(_EvalModel):
    levels: list[HnswLevelReport]
    distinct_vector_control: HnswLevelReport


class GateCheckResult(_EvalModel):
    name: _Text
    observed: float | None
    threshold: float
    sample_count: NonNegativeInt
    passed: bool

    @model_validator(mode="after")
    def _check_passing_result(self) -> Self:
        if self.passed and (self.observed is None or self.sample_count == 0):
            raise ValueError("A passing gate requires an observed value and a nonempty population.")
        return self


class EvaluationReport(_EvalModel):
    provenance: EvalProvenance
    modes: dict[SearchMode, ModeMetrics]
    records: list[QuestionEvalRecord]
    threshold_sweep: ThresholdSweepReport | None = None
    hnsw_duplicate_probe: HnswDuplicateReport | None = None
    gates: list[GateCheckResult] = Field(default_factory=list)
