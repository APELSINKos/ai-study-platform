"""Citation verification, marker renumbering and strict grounding for RAG chat answers.

Model output is untrusted: every [S1] / [S1, S2] marker is validated against the passages in
BuiltContext, mapped to contiguous 1-based display indices [1]..[k], and backed by immutable
CitationSnapshot records. If a non-refusal answer has no surviving valid citations or becomes
blank after cleaning, its prose is discarded completely in favour of a safe fallback.
"""

import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from app.documents.cleaning import NFC_PIECE_MAX_CHARS
from app.documents.text import ELLIPSIS, shorten
from app.llm.schemas import ChatAnswer
from app.rag.context import BuiltContext
from app.rag.retriever import RetrievedChunk

MAX_ANSWER_CHARS: Final = 8_000
MAX_CITATION_QUOTE_CHARS: Final = 320
INSUFFICIENT_CONTEXT_FALLBACK: Final = (
    "The uploaded materials do not contain enough information to answer this question."
)

# Linear possessive matcher for [S1], [S1, S2], [S1; S2] groups; never backtracks across runs
# such as "[S1," repeated two million times.
SOURCE_GROUP_RE: Final = re.compile(r"\[\s*+S\d{1,3}(?:\s*+[,;]\s*+S\d{1,3})*+\s*+\]")
_SOURCE_LABEL_RE: Final = re.compile(r"S\d{1,3}")
_DISPLAY_MARKER_RE: Final = re.compile(r"\[\d{1,3}\]")
# Maximum length of a display citation marker such as "[123]" (5 chars).
_MAX_DISPLAY_MARKER_CHARS: Final = 5
_LINE_BREAK_RE: Final = re.compile(
    r"\r\n?|[\v\f\x1c-\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]"
)
_NO_BREAK_SPACES: Final = ("\N{NO-BREAK SPACE}", "\N{NARROW NO-BREAK SPACE}", "\t")
# Control, format and lone-surrogate categories dropped from stored text.
_DROPPED_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs"})
_ORPHAN_PUNCTUATION: Final = ".,;:!?"
_HORIZONTAL_SPACE: Final = " \t"
_TRAILING_SEPARATORS: Final = " \t\r\n,;:-\u2013\u2014"


@dataclass(frozen=True, slots=True)
class CitationSnapshot:
    """Immutable passage reference stored on an assistant chat message."""

    index: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    chunk_index: int
    heading: str | None
    page_start: int | None
    page_end: int | None
    quote: str

    def to_json(self) -> dict[str, object]:
        """JSON-serializable representation for chat_messages.citations JSONB."""
        return {
            "index": self.index,
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "document_title": self.document_title,
            "chunk_index": self.chunk_index,
            "heading": self.heading,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "quote": self.quote,
        }


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """Verified answer text, ordered citation snapshots and grounding status."""

    content: str
    citations: tuple[CitationSnapshot, ...]
    insufficient_context: bool
    grounding_overridden: bool


def clean_chat_text(text: str) -> str:
    """Normalize line breaks, drop control/format/surrogate chars, preserve paragraphs and NFC."""
    return _finalize_paragraphs(_normalize_raw_text(text))


def ground_answer(raw: ChatAnswer, context: BuiltContext) -> GroundedAnswer:
    """Validate and renumber citations in raw against context, enforcing strict grounding."""
    normalized_text = _normalize_raw_text(raw.answer)
    if raw.insufficient_context:
        stripped = _rewrite_groups(normalized_text, lambda _match: "")
        cleaned = _finalize_paragraphs(stripped)
        if cleaned:
            cleaned = _truncate_preserving_citations(cleaned, MAX_ANSWER_CHARS)
        return GroundedAnswer(
            content=cleaned or INSUFFICIENT_CONTEXT_FALLBACK,
            citations=(),
            insufficient_context=True,
            grounding_overridden=False,
        )

    sources_by_label = {source.label: source for source in context.sources}
    ordered_labels: list[str] = []
    seen_labels: set[str] = set()

    for match in SOURCE_GROUP_RE.finditer(normalized_text):
        for label in _SOURCE_LABEL_RE.findall(match.group()):
            if label in sources_by_label and label not in seen_labels:
                seen_labels.add(label)
                ordered_labels.append(label)

    for entry in raw.citations:
        normalized_label = entry.strip().strip("[]").strip().upper()
        if normalized_label in sources_by_label and normalized_label not in seen_labels:
            seen_labels.add(normalized_label)
            ordered_labels.append(normalized_label)

    label_to_index = {label: index for index, label in enumerate(ordered_labels, start=1)}

    def _replace_group(match: re.Match[str]) -> str:
        group_seen: set[str] = set()
        markers: list[str] = []
        for label in _SOURCE_LABEL_RE.findall(match.group()):
            index = label_to_index.get(label)
            if index is not None and label not in group_seen:
                group_seen.add(label)
                markers.append(f"[{index}]")
        return "".join(markers)

    rewritten = _rewrite_groups(normalized_text, _replace_group)
    cleaned = _finalize_paragraphs(rewritten)
    if cleaned:
        cleaned = _truncate_preserving_citations(cleaned, MAX_ANSWER_CHARS)

    if not ordered_labels or not cleaned:
        return GroundedAnswer(
            content=INSUFFICIENT_CONTEXT_FALLBACK,
            citations=(),
            insufficient_context=True,
            grounding_overridden=True,
        )

    snapshots = tuple(
        _citation_snapshot(label_to_index[label], sources_by_label[label].chunk)
        for label in ordered_labels
    )
    return GroundedAnswer(
        content=cleaned,
        citations=snapshots,
        insufficient_context=False,
        grounding_overridden=False,
    )


def _rewrite_groups(text: str, replacer: Callable[[re.Match[str]], str]) -> str:
    """Replace SOURCE_GROUP_RE matches in one pass, cleaning spacing where a group is removed."""
    pieces: list[str] = []
    last = 0
    prev_removed = False
    for match in SOURCE_GROUP_RE.finditer(text):
        literal = text[last : match.start()]
        replacement = replacer(match)
        last = match.end()
        if prev_removed:
            if not replacement and not literal.strip(_HORIZONTAL_SPACE):
                # Consecutive removed groups separated by nothing or spaces collapse as one gap.
                continue
            literal = _join_after_removed(pieces, literal)
            prev_removed = False
        if literal:
            pieces.append(literal)
        if replacement:
            pieces.append(replacement)
        else:
            prev_removed = True
    tail = text[last:]
    if prev_removed:
        tail = _join_after_removed(pieces, tail)
    if tail:
        pieces.append(tail)
    return "".join(pieces)


def _join_after_removed(pieces: list[str], following: str) -> str:
    """Clean orphan spaces left between the text before a removed marker and what follows it."""
    if not following or following[0] in _ORPHAN_PUNCTUATION or following[0] == "\n":
        _strip_trailing_horizontal_space(pieces)
        return following
    if not pieces or pieces[-1].endswith("\n") or pieces[-1][-1] in _HORIZONTAL_SPACE:
        return following.lstrip(_HORIZONTAL_SPACE)
    return following


def _strip_trailing_horizontal_space(pieces: list[str]) -> None:
    while pieces:
        trimmed = pieces[-1].rstrip(_HORIZONTAL_SPACE)
        if trimmed:
            pieces[-1] = trimmed
            return
        pieces.pop()


def _normalize_raw_text(text: str) -> str:
    """Normalize line breaks and drop control, format and surrogate characters."""
    text = _LINE_BREAK_RE.sub("\n", text)
    for space in _NO_BREAK_SPACES:
        text = text.replace(space, " ")
    cleaned_lines: list[str] = []
    for raw_line in text.split("\n"):
        if raw_line.isprintable():
            cleaned_lines.append(raw_line)
        else:
            cleaned_lines.append(
                "".join(
                    char
                    for char in raw_line
                    if unicodedata.category(char) not in _DROPPED_CATEGORIES
                )
            )
    return "\n".join(cleaned_lines)


def _finalize_paragraphs(text: str) -> str:
    """Collapse per-line horizontal whitespace, preserve \\n\\n paragraphs and compose to NFC."""
    lines: list[str] = []
    blank_pending = False
    for raw_line in text.split("\n"):
        line = " ".join(raw_line.split())
        if not line:
            if lines:
                blank_pending = True
            continue
        if blank_pending:
            lines.append("")
            blank_pending = False
        lines.append(line)
    if not lines:
        return ""
    return _compose_nfc("\n".join(lines))


def _compose_nfc(text: str) -> str:
    """Compose text to NFC in bounded chunks so hostile runs stay linear."""
    pieces: list[str] = []
    start = 0
    while len(text) - start > NFC_PIECE_MAX_CHARS:
        limit = start + NFC_PIECE_MAX_CHARS
        end = max(text.rfind("\n", start + 1, limit + 1), text.rfind(" ", start + 1, limit + 1))
        if end <= start:
            end = limit
            for pos in range(limit, start, -1):
                if not unicodedata.combining(text[pos]):
                    end = pos
                    break
        pieces.append(unicodedata.normalize("NFC", text[start:end]))
        start = end
    pieces.append(unicodedata.normalize("NFC", text[start:]))
    return "".join(pieces)


def _truncate_preserving_citations(text: str, max_chars: int) -> str:
    """Cap text to max_chars at a word boundary without cutting a [12] citation marker in half."""
    if len(text) <= max_chars:
        return text
    limit = max_chars - len(ELLIPSIS)
    cut = text[:limit]
    if not (cut[-1:].isspace() or text[limit].isspace()):
        parts = cut.rsplit(maxsplit=1)
        if len(parts) > 1:
            cut = parts[0]
        else:
            # No whitespace in prefix: step back if the cut landed inside a [12] marker.
            search_from = max(0, len(cut) - _MAX_DISPLAY_MARKER_CHARS + 1)
            open_pos = cut.rfind("[", search_from)
            if open_pos != -1 and "]" not in cut[open_pos:]:
                close_pos = text.find("]", open_pos, open_pos + _MAX_DISPLAY_MARKER_CHARS)
                if close_pos != -1 and _DISPLAY_MARKER_RE.fullmatch(text[open_pos : close_pos + 1]):
                    cut = cut[:open_pos]
    return cut.rstrip(_TRAILING_SEPARATORS) + ELLIPSIS


def _citation_snapshot(index: int, chunk: RetrievedChunk) -> CitationSnapshot:
    if any(part.highlighted for part in chunk.snippet):
        raw_quote = "".join(part.text for part in chunk.snippet)
    else:
        raw_quote = chunk.content
    quote = shorten(" ".join(raw_quote.split()), MAX_CITATION_QUOTE_CHARS)
    return CitationSnapshot(
        index=index,
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_title=chunk.document_title,
        chunk_index=chunk.chunk_index,
        heading=chunk.heading,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        quote=quote,
    )
