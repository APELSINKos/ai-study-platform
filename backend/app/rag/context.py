"""Context budgeting for RAG chat: assigns S1..Sn labels within a fixed character budget."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.documents.text import ELLIPSIS, shorten
from app.llm.base import ChatContextPassage
from app.rag.retriever import RetrievedChunk

MAX_CONTEXT_CHARS: Final = 12_000


@dataclass(frozen=True, slots=True)
class ContextSource:
    """One retrieved chunk with its server-assigned label and prompt-budgeted content.

    chunk is kept unmodified so citation snapshots always quote the original passage.
    """

    label: str
    chunk: RetrievedChunk
    prompt_content: str


@dataclass(frozen=True, slots=True)
class BuiltContext:
    """The ranked passages selected for a chat prompt within the context character budget."""

    sources: tuple[ContextSource, ...]
    total_chars: int

    def to_chat_passages(self) -> tuple[ChatContextPassage, ...]:
        """Convert selected sources into provider-ready passages."""
        return tuple(
            ChatContextPassage(
                label=source.label,
                document_title=source.chunk.document_title,
                heading=source.chunk.heading,
                page_start=source.chunk.page_start,
                page_end=source.chunk.page_end,
                content=source.prompt_content,
            )
            for source in self.sources
        )


def build_context(
    chunks: Sequence[RetrievedChunk], *, max_chars: int = MAX_CONTEXT_CHARS
) -> BuiltContext:
    """Pack retrieved chunks in rank order under labels S1..Sn up to max_chars.

    S1 is always included; if S1 alone exceeds max_chars, only its prompt_content is truncated
    at a word boundary while source.chunk remains intact for citation snapshots.
    """
    if max_chars < len(ELLIPSIS):
        raise ValueError(f"max_chars must be at least {len(ELLIPSIS)}, got {max_chars}")
    if not chunks:
        return BuiltContext(sources=(), total_chars=0)

    first = chunks[0]
    first_content = (
        shorten(first.content, max_chars) if len(first.content) > max_chars else first.content
    )
    sources = [ContextSource(label="S1", chunk=first, prompt_content=first_content)]
    total_chars = len(first_content)

    for rank, chunk in enumerate(chunks[1:], start=2):
        if total_chars + len(chunk.content) > max_chars:
            break
        sources.append(ContextSource(label=f"S{rank}", chunk=chunk, prompt_content=chunk.content))
        total_chars += len(chunk.content)

    return BuiltContext(sources=tuple(sources), total_chars=total_chars)
