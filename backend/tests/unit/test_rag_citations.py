# ruff: noqa: RUF001 -- Russian sample text is intended

import json
import time
import uuid
from typing import Final

import pytest

from app.documents.text import ELLIPSIS
from app.llm.schemas import ChatAnswer
from app.rag.citations import (
    INSUFFICIENT_CONTEXT_FALLBACK,
    MAX_ANSWER_CHARS,
    MAX_CITATION_QUOTE_CHARS,
    SOURCE_GROUP_RE,
    CitationSnapshot,
    GroundedAnswer,
    ground_answer,
)
from app.rag.context import build_context
from app.rag.retriever import RetrievedChunk
from app.schemas.search import SnippetPart

_DOC_ID: Final = uuid.UUID("8e2a4c71-0f5d-4b96-b3e8-6d1a9c4f7e20")
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0


def _chunk(
    index: int,
    content: str,
    *,
    snippet: list[SnippetPart] | None = None,
    heading: str | None = "Heading",
    pages: tuple[int | None, int | None] = (1, 2),
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.UUID(int=index + 1),
        document_id=_DOC_ID,
        document_title=f"Document {index + 1}",
        chunk_index=index,
        heading=heading,
        page_start=pages[0],
        page_end=pages[1],
        content=content,
        char_count=len(content),
        snippet=snippet or [SnippetPart(text=content[:30], highlighted=False)],
        score=1 / (60 + index + 1),
        matched_by=("keyword", "semantic"),
        similarity=0.75,
        keyword_rank=0.5,
    )


def test_renumbers_inline_and_grouped_citations_in_order_of_first_appearance() -> None:
    context = build_context(
        [
            _chunk(
                0,
                "First chunk full content.",
                snippet=[
                    SnippetPart(text="First ", highlighted=False),
                    SnippetPart(text="chunk", highlighted=True),
                    SnippetPart(text=" snippet.", highlighted=False),
                ],
            ),
            _chunk(1, "Second chunk\n  with   extra spaces.", heading="Section 2", pages=(3, 3)),
            _chunk(2, "Third chunk content.", heading=None, pages=(None, None)),
        ]
    )
    raw = ChatAnswer(
        answer="Start with [S2, S1]. Repeat [S1; S2] and drop invalid [S1, S99].",
        citations=[" [s3] ", "S99"],
        insufficient_context=False,
    )

    grounded = ground_answer(raw, context)

    assert grounded.insufficient_context is False
    assert grounded.grounding_overridden is False
    assert grounded.content == "Start with [1][2]. Repeat [2][1] and drop invalid [2]."
    assert [citation.index for citation in grounded.citations] == [1, 2, 3]
    assert [citation.chunk_index for citation in grounded.citations] == [1, 0, 2]
    # Highlighted snippet is used for chunk 0; chunk content is collapsed for chunk 1.
    assert grounded.citations[0].quote == "Second chunk with extra spaces."
    assert grounded.citations[1].quote == "First chunk snippet."
    assert grounded.citations[2].quote == "Third chunk content."


def test_citation_snapshot_to_json_produces_json_serializable_dict_with_string_uuids() -> None:
    context = build_context([_chunk(0, "Review slows forgetting.")])
    raw = ChatAnswer(answer="Review helps [S1].", citations=["S1"], insufficient_context=False)

    grounded = ground_answer(raw, context)
    (citation,) = grounded.citations
    payload = citation.to_json()

    assert isinstance(citation, CitationSnapshot)
    assert payload == {
        "index": 1,
        "chunk_id": str(uuid.UUID(int=1)),
        "document_id": str(_DOC_ID),
        "document_title": "Document 1",
        "chunk_index": 0,
        "heading": "Heading",
        "page_start": 1,
        "page_end": 2,
        "quote": "Review slows forgetting.",
    }
    assert json.loads(json.dumps(payload)) == payload


def test_unknown_markers_are_removed_without_leaving_orphan_spaces_before_punctuation() -> None:
    context = build_context([_chunk(0, "Valid source.")])
    raw = ChatAnswer(
        answer=(
            "Grounded fact [S1]. Unknown [S99]. Comma [S98], semi [S97]; "
            "middle [S96] continues and pair [S95] [S94]!"
        ),
        citations=["S1", "S99"],
        insufficient_context=False,
    )

    grounded = ground_answer(raw, context)

    assert grounded.content == (
        "Grounded fact [1]. Unknown. Comma, semi; middle continues and pair!"
    )
    assert [citation.index for citation in grounded.citations] == [1]


def test_normalizes_citations_list_even_when_model_omitted_inline_markers() -> None:
    context = build_context([_chunk(0, "Source one."), _chunk(1, "Source two.")])
    raw = ChatAnswer(
        answer="Grounded summary without inline tags.",
        citations=[" [s2] ", "s1", "S99"],
        insufficient_context=False,
    )

    grounded = ground_answer(raw, context)

    assert grounded.insufficient_context is False
    assert grounded.grounding_overridden is False
    assert grounded.content == "Grounded summary without inline tags."
    assert [(c.index, c.chunk_index) for c in grounded.citations] == [(1, 1), (2, 0)]


@pytest.mark.parametrize(
    "raw",
    [
        ChatAnswer(
            answer="Hallucinated claim [S99].", citations=["S99"], insufficient_context=False
        ),
        ChatAnswer(answer="Unsupported guess.", citations=[], insufficient_context=False),
        ChatAnswer(answer="   [S99]  ", citations=["S1"], insufficient_context=False),
        ChatAnswer(answer=" \x00\u200b ", citations=["S1"], insufficient_context=False),
    ],
    ids=["only-unknown-citation", "no-citations", "blank-after-strip", "blank-invisible"],
)
def test_strict_grounding_guard_discards_ungrounded_or_blank_answers(raw: ChatAnswer) -> None:
    context = build_context([_chunk(0, "Real passage.")])

    grounded = ground_answer(raw, context)

    assert grounded == GroundedAnswer(
        content=INSUFFICIENT_CONTEXT_FALLBACK,
        citations=(),
        insufficient_context=True,
        grounding_overridden=True,
    )


def test_honest_insufficient_context_strips_stray_markers_and_preserves_explanation() -> None:
    context = build_context([_chunk(0, "Real passage.")])
    raw = ChatAnswer(
        answer="Материалы не покрывают этот вопрос [S1].\r\n\r\nПопробуйте другой документ [S2]!",
        citations=["S1"],
        insufficient_context=True,
    )

    grounded = ground_answer(raw, context)

    assert grounded == GroundedAnswer(
        content="Материалы не покрывают этот вопрос.\n\nПопробуйте другой документ!",
        citations=(),
        insufficient_context=True,
        grounding_overridden=False,
    )


def test_honest_insufficient_context_with_blank_answer_uses_fallback() -> None:
    context = build_context([_chunk(0, "Real passage.")])
    raw = ChatAnswer(answer="  [S1] \x00 ", citations=["S1"], insufficient_context=True)

    grounded = ground_answer(raw, context)

    assert grounded == GroundedAnswer(
        content=INSUFFICIENT_CONTEXT_FALLBACK,
        citations=(),
        insufficient_context=True,
        grounding_overridden=False,
    )


def test_normalizes_control_chars_nul_and_surrogates_while_preserving_paragraphs() -> None:
    context = build_context([_chunk(0, "Source text.")])
    raw = ChatAnswer(
        answer="First\x00 para\u202e [S1].\r\n\r\n\r\nSecond\ud800  para\u200b [S1].\nNext line.",
        citations=["S1"],
        insufficient_context=False,
    )

    grounded = ground_answer(raw, context)

    assert grounded.content == "First para [1].\n\nSecond para [1].\nNext line."


def test_caps_long_answer_without_splitting_citation_markers_mid_token() -> None:
    chunks = [_chunk(index, f"Passage {index}.") for index in range(12)]
    context = build_context(chunks)
    # Build an answer with a 2-digit citation [12] positioned right across the 8,000-char boundary.
    intro = " ".join(f"[S{index}]" for index in range(1, 12)) + " "
    body_word = "a" * (MAX_ANSWER_CHARS - len(intro) - 2)
    raw = ChatAnswer(
        answer=f"{intro}{body_word}[S12] trailing text",
        citations=[f"S{index}" for index in range(1, 13)],
        insufficient_context=False,
    )

    grounded = ground_answer(raw, context)

    assert len(grounded.content) <= MAX_ANSWER_CHARS
    assert grounded.content.endswith(ELLIPSIS)
    # No unclosed "[" or partial "[1…" marker at the cut point.
    assert grounded.content.count("[") == grounded.content.count("]")
    assert "[1…" not in grounded.content


def test_caps_long_answer_without_whitespace_before_marker_at_boundary() -> None:
    chunks = [_chunk(index, f"Passage {index}.") for index in range(12)]
    context = build_context(chunks)
    prefix = "".join(f"[S{index}]" for index in range(1, 12))
    # Length of prefix after renumbering: [1]..[9] = 27 chars, [10][11] = 8 chars -> 35 chars.
    # Place [12] at index 7997..8000 so limit=7999 falls inside [12].
    filler = "x" * (MAX_ANSWER_CHARS - 35 - 3)
    raw = ChatAnswer(
        answer=f"{prefix}{filler}[S12]tail",
        citations=[f"S{index}" for index in range(1, 13)],
        insufficient_context=False,
    )

    grounded = ground_answer(raw, context)

    assert len(grounded.content) <= MAX_ANSWER_CHARS
    assert grounded.content.endswith(ELLIPSIS)
    assert grounded.content.count("[") == grounded.content.count("]")
    assert not grounded.content.endswith("[1" + ELLIPSIS)


def test_citation_quote_is_capped_at_word_boundary() -> None:
    long_chunk = _chunk(0, " ".join(f"word{index}" for index in range(120)))
    context = build_context([long_chunk])
    raw = ChatAnswer(answer="See [S1].", citations=["S1"], insufficient_context=False)

    grounded = ground_answer(raw, context)

    quote = grounded.citations[0].quote
    assert len(quote) <= MAX_CITATION_QUOTE_CHARS
    assert quote.endswith(ELLIPSIS)


@pytest.mark.no_cover
@pytest.mark.parametrize(
    "hostile",
    [
        "[S1," * 500_000,
        "[S1" + ", S1" * 499_999,
        "[" + " " * 1_999_999,
    ],
    ids=["repeated-unclosed-groups", "one-giant-unclosed-group", "open-bracket-and-spaces"],
)
def test_source_group_regex_and_grounding_stay_linear_on_two_million_chars(hostile: str) -> None:
    context = build_context([_chunk(0, "Source text.")])

    started = time.perf_counter()
    assert SOURCE_GROUP_RE.findall(hostile) == []
    grounded = ground_answer(
        ChatAnswer(answer=f"Fact [S1]. {hostile}", citations=["S1"], insufficient_context=False),
        context,
    )

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
    assert grounded.insufficient_context is False
    assert len(grounded.content) <= MAX_ANSWER_CHARS
