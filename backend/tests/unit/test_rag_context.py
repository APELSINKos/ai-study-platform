import uuid
from typing import Final

import pytest

from app.documents.text import ELLIPSIS
from app.llm.base import ChatContextPassage
from app.rag.context import MAX_CONTEXT_CHARS, BuiltContext, ContextSource, build_context
from app.rag.retriever import RetrievedChunk
from app.schemas.search import SnippetPart

_DOC_ID: Final = uuid.UUID("8e2a4c71-0f5d-4b96-b3e8-6d1a9c4f7e20")


def _chunk(index: int, content: str, *, heading: str | None = "Section") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.UUID(int=index),
        document_id=_DOC_ID,
        document_title="Study notes",
        chunk_index=index,
        heading=heading,
        page_start=index + 1,
        page_end=index + 2,
        content=content,
        char_count=len(content),
        snippet=[SnippetPart(text=content[:40], highlighted=False)],
        score=1 / (60 + index + 1),
        matched_by=("semantic",),
        similarity=0.8,
        keyword_rank=None,
    )


def test_empty_chunks_build_empty_context() -> None:
    context = build_context([])

    assert context == BuiltContext(sources=(), total_chars=0)
    assert context.to_chat_passages() == ()


def test_assigns_sequential_labels_within_budget_and_converts_to_chat_passages() -> None:
    first = _chunk(0, "First passage.", heading="Intro")
    second = _chunk(1, "Second passage.", heading=None)
    third = _chunk(2, "Third passage that exceeds budget.")

    context = build_context([first, second, third], max_chars=35)

    assert [source.label for source in context.sources] == ["S1", "S2"]
    assert context.total_chars == len("First passage.") + len("Second passage.")
    assert context.to_chat_passages() == (
        ChatContextPassage(
            label="S1",
            document_title="Study notes",
            heading="Intro",
            page_start=1,
            page_end=2,
            content="First passage.",
        ),
        ChatContextPassage(
            label="S2",
            document_title="Study notes",
            heading=None,
            page_start=2,
            page_end=3,
            content="Second passage.",
        ),
    )


def test_always_keeps_s1_truncating_only_prompt_content_while_preserving_chunk() -> None:
    long_content = " ".join(f"word{index}" for index in range(100))
    first = _chunk(0, long_content)
    second = _chunk(1, "Short second chunk.")

    context = build_context([first, second], max_chars=50)

    assert len(context.sources) == 1
    source = context.sources[0]
    assert isinstance(source, ContextSource)
    assert source.label == "S1"
    assert len(source.prompt_content) <= 50
    assert source.prompt_content.endswith(ELLIPSIS)
    assert context.total_chars == len(source.prompt_content)
    # The underlying RetrievedChunk stays intact for citation snapshots.
    assert source.chunk is first
    assert source.chunk.content == long_content
    assert context.to_chat_passages()[0].content == source.prompt_content


def test_stops_at_first_chunk_that_overflows_budget_without_skipping_ranks() -> None:
    chunks = [
        _chunk(0, "a" * 60),
        _chunk(1, "b" * 50),
        _chunk(2, "c" * 10),
    ]

    context = build_context(chunks, max_chars=100)

    assert [source.label for source in context.sources] == ["S1"]
    assert context.total_chars == 60


def test_default_budget_matches_documented_limit_and_rejects_non_positive_limit() -> None:
    assert MAX_CONTEXT_CHARS == 12_000
    with pytest.raises(ValueError, match="max_chars"):
        build_context([], max_chars=0)
