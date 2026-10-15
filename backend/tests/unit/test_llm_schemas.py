import json
from typing import Any, Final

import pytest
from pydantic import ValidationError

from app.documents.text import ELLIPSIS
from app.llm.schemas import (
    MAX_TOPICS,
    TOPIC_MAX_LENGTH,
    DocumentAnalysis,
    NormalizedAnalysis,
    normalize_analysis,
)
from app.models.document import DIFFICULTIES, SUMMARY_MAX_LENGTH, TITLE_MAX_LENGTH

VALID_ANALYSIS: Final[dict[str, Any]] = {
    "title": "Spaced repetition",
    "summary": "Reviews are scheduled just before you forget.",
    "topics": ["intervals", "flashcards"],
    "difficulty": "medium",
}


def _analysis(**changes: Any) -> DocumentAnalysis:
    return DocumentAnalysis.model_validate(VALID_ANALYSIS | changes)


def test_the_wire_schema_is_strict() -> None:
    schema = DocumentAnalysis.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == set(VALID_ANALYSIS)
    assert schema["properties"]["topics"]["minItems"] == 1
    assert schema["properties"]["topics"]["maxItems"] == MAX_TOPICS


def test_the_wire_schema_has_no_defaults_and_no_string_lengths() -> None:
    schema_text = json.dumps(DocumentAnalysis.model_json_schema())

    for keyword in ('"default"', '"maxLength"', '"minLength"'):
        assert keyword not in schema_text


def test_difficulty_is_a_bare_reference_to_the_shared_values() -> None:
    schema = DocumentAnalysis.model_json_schema()

    # Strict structured output rejects any keyword placed next to a $ref.
    assert schema["properties"]["difficulty"] == {"$ref": "#/$defs/Difficulty"}
    assert schema["$defs"]["Difficulty"]["enum"] == list(DIFFICULTIES)


def test_a_valid_analysis_is_accepted() -> None:
    analysis = _analysis()

    assert analysis.model_dump() == VALID_ANALYSIS


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": "field"},
        {"difficulty": "expert"},
        {"topics": []},
        {"topics": [f"topic {number}" for number in range(MAX_TOPICS + 1)]},
        {"title": None},
    ],
    ids=["unknown-field", "unknown-difficulty", "no-topics", "too-many-topics", "null-title"],
)
def test_an_invalid_analysis_is_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _analysis(**changes)


@pytest.mark.parametrize("missing", sorted(VALID_ANALYSIS))
def test_every_field_is_required(missing: str) -> None:
    values = {key: value for key, value in VALID_ANALYSIS.items() if key != missing}

    with pytest.raises(ValidationError):
        DocumentAnalysis.model_validate(values)


def test_a_clean_analysis_is_kept_as_it_is() -> None:
    assert normalize_analysis(_analysis()) == NormalizedAnalysis(
        title="Spaced repetition",
        summary="Reviews are scheduled just before you forget.",
        topics=["intervals", "flashcards"],
        difficulty="medium",
    )


def test_whitespace_is_collapsed_everywhere() -> None:
    normalized = normalize_analysis(
        _analysis(
            title="  Spaced \n\t repetition  ",
            summary="First line.\n\nSecond\u00a0 line.",
            topics=["  spaced \u2003 repetition "],
        )
    )

    assert normalized.title == "Spaced repetition"
    assert normalized.summary == "First line. Second line."
    assert normalized.topics == ["spaced repetition"]


def test_control_and_format_characters_are_removed() -> None:
    normalized = normalize_analysis(
        _analysis(title="Ti\x00tle\u200b of\u202e notes", topics=["in\x07ter\u2066vals"])
    )

    assert normalized.title == "Title of notes"
    assert normalized.topics == ["intervals"]


def test_lone_surrogates_are_removed_so_the_text_can_be_stored() -> None:
    normalized = normalize_analysis(
        _analysis(title="Ti\ud800tle", summary="Short\udfff summary.", topics=["inter\udc80vals"])
    )

    assert normalized.title == "Title"
    assert normalized.summary == "Short summary."
    assert normalized.topics == ["intervals"]


def test_text_is_composed_to_nfc() -> None:
    normalized = normalize_analysis(_analysis(title="\u0415\u0308\u043b\u043a\u0430"))

    assert normalized.title == "\u0401\u043b\u043a\u0430"


def test_a_blank_title_or_summary_becomes_none() -> None:
    normalized = normalize_analysis(_analysis(title=" \n\t ", summary="\u200b"))

    assert normalized.title is None
    assert normalized.summary is None


@pytest.mark.parametrize(
    ("field", "max_length"),
    [("title", TITLE_MAX_LENGTH), ("summary", SUMMARY_MAX_LENGTH)],
)
def test_long_text_is_cut_at_a_word_boundary(field: str, max_length: int) -> None:
    normalized = normalize_analysis(_analysis(**{field: "Interval " * 400}))
    value = getattr(normalized, field)

    assert len(value) <= max_length
    assert value.endswith(ELLIPSIS)
    assert set(value.removesuffix(ELLIPSIS).split(" ")) == {"Interval"}


def test_topics_are_trimmed_deduplicated_cut_and_capped() -> None:
    raw_topics = [
        " Интервалы ",
        "интервалы",
        "   ",
        "Repetition",
        "REPETITION",
        "a" * 70,
        *(f"topic {number}" for number in range(10)),
    ]
    # Built without validation: a model is allowed at most eight topics.
    analysis = DocumentAnalysis.model_construct(**(VALID_ANALYSIS | {"topics": raw_topics}))

    normalized = normalize_analysis(analysis)

    assert normalized.topics == [
        "Интервалы",
        "Repetition",
        "a" * (TOPIC_MAX_LENGTH - 1) + ELLIPSIS,
        "topic 0",
        "topic 1",
        "topic 2",
        "topic 3",
        "topic 4",
    ]
    assert len(normalized.topics) == MAX_TOPICS


def test_normalizing_twice_changes_nothing() -> None:
    once = normalize_analysis(
        _analysis(
            title="  A " + "very long title " * 30,
            summary="Summary\n" * 200,
            topics=["  B ", "b", "c" * 80],
            difficulty="hard",
        )
    )
    assert once.title is not None
    assert once.summary is not None

    twice = normalize_analysis(
        DocumentAnalysis(
            title=once.title, summary=once.summary, topics=once.topics, difficulty=once.difficulty
        )
    )

    assert twice == once
