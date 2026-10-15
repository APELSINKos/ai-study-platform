"""Splitting cleaned document text into chunks for search and citations.

A chunk holds whole sentences, at most size characters of them, after the last sentences of
the chunk before it that fit in overlap characters, so a passage at a chunk boundary is
still found with its context. A sentence longer than size is cut between words, and a run
without spaces every size characters, so no chunk is ever longer than size + overlap.
Chunks are slices of the text, line breaks included. Everything here runs on untrusted
text and stays linear on hostile input.
"""

import re
from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from app.documents.text import shorten, split_sentences
from app.models.document_chunk import CHUNK_HEADING_MAX_LENGTH

HEADING_SEPARATOR: Final = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "
# A sentence can go on from one page to the next, so pages are joined by a line break
# rather than by a blank line, which ends a sentence.
PAGE_SEPARATOR: Final = "\n"
MARKDOWN_MAX_HEADING_LEVEL: Final = 6
_CODE_FENCES: Final = ("```", "~~~")
# A line that may be a heading or a code fence: up to three spaces, then "#", "```" or "~~~".
# Only these lines are examined one by one, so other lines cost no Python work.
_MARKDOWN_LINE_RE: Final = re.compile(r"^ {0,3}+(?:#|```|~~~)", re.MULTILINE)
# A line break followed by one or more blank lines: the end of a paragraph.
_PARAGRAPH_BREAK_RE: Final = re.compile(r"\n(?:[^\S\n]*+\n)++")
_NON_SPACE_RE: Final = re.compile(r"\S")

# Where a piece of a text is: its start and end offsets.
type Span = tuple[int, int]
type _Section = tuple[tuple[str, ...], int, int]


@dataclass(frozen=True, slots=True)
class Chunk:
    """A passage of a document; pages count from 1 and are known only for a PDF."""

    index: int
    content: str
    heading: str | None
    page_start: int | None
    page_end: int | None
    char_count: int


def chunk_plain(text: str, *, size: int, overlap: int) -> list[Chunk]:
    """Chunks of plain text, which has neither headings nor pages."""
    _check_sizes(size, overlap)
    return [
        _chunk(text, index, span, heading=None)
        for index, span in enumerate(_chunk_spans(text, 0, len(text), size, overlap))
    ]


def chunk_markdown(text: str, *, size: int, overlap: int) -> list[Chunk]:
    """Chunks of a Markdown document, each with the path of the headings it falls under.

    Heading lines stay out of the chunks, and a chunk never spans two sections; "#" lines
    inside code blocks are not headings. A document of headings alone is chunked as plain
    text, so its text still gets chunks.
    """
    _check_sizes(size, overlap)
    chunks: list[Chunk] = []
    for titles, start, end in _markdown_sections(text):
        heading = _heading_path(titles)
        for span in _chunk_spans(text, start, end, size, overlap):
            chunks.append(_chunk(text, len(chunks), span, heading))
    return chunks or chunk_plain(text, size=size, overlap=overlap)


def chunk_pdf_pages(pages: Sequence[str], *, size: int, overlap: int) -> list[Chunk]:
    """Chunks of the pages of a PDF, each with the first and the last page it comes from.

    A chunk may run on from one page to the next. A page without text keeps its number.
    """
    _check_sizes(size, overlap)
    text = PAGE_SEPARATOR.join(pages)
    page_starts: list[int] = []
    offset = 0
    for page in pages:
        page_starts.append(offset)
        offset += len(page) + len(PAGE_SEPARATOR)
    # A chunk starts and ends with a non-space character, so never inside a separator.
    return [
        Chunk(
            index=index,
            content=text[start:end],
            heading=None,
            page_start=bisect_right(page_starts, start),
            page_end=bisect_right(page_starts, end - 1),
            char_count=end - start,
        )
        for index, (start, end) in enumerate(_chunk_spans(text, 0, len(text), size, overlap))
    ]


def sentence_spans(text: str, start: int, end: int, *, max_chars: int) -> list[Span]:
    """Where the sentences of text[start:end] are, in reading order.

    A blank line ends a sentence as well. A sentence longer than max_chars comes in parts
    of at most max_chars, cut between words or, in a run without spaces, every max_chars
    characters.
    """
    if max_chars < 1:
        raise ValueError(f"max_chars must be positive, got {max_chars}")
    spans: list[Span] = []
    for paragraph_start, paragraph_end in _paragraphs(text, start, end):
        paragraph = text[paragraph_start:paragraph_end]
        position = 0
        for sentence in split_sentences(paragraph):
            # Sentences come trimmed and in order with only spaces between them, so each
            # one is found right after the spaces that follow the one before.
            sentence_start = paragraph.index(sentence, position)
            position = sentence_start + len(sentence)
            spans.extend(
                _cut(text, paragraph_start + sentence_start, paragraph_start + position, max_chars)
            )
    return spans


def _check_sizes(size: int, overlap: int) -> None:
    if size < 1 or overlap < 0:
        raise ValueError(f"size must be positive and overlap not negative, got {size}, {overlap}")


def _chunk(text: str, index: int, span: Span, heading: str | None) -> Chunk:
    start, end = span
    return Chunk(
        index=index,
        content=text[start:end],
        heading=heading,
        page_start=None,
        page_end=None,
        char_count=end - start,
    )


def _chunk_spans(text: str, start: int, end: int, size: int, overlap: int) -> list[Span]:
    """Where the chunks of text[start:end] are.

    Sentences are added while the text from the first new one fits in size; before them
    come the previous chunk's last sentences whose text, up to the first new one, fits in
    overlap.
    """
    sentences = sentence_spans(text, start, end, max_chars=size)
    chunks: list[Span] = []
    previous_first = 0
    first_new = 0
    while first_new < len(sentences):
        new_start = sentences[first_new][0]
        first = first_new
        # The overlap stops short of the previous chunk's first sentence; reaching it
        # would repeat that whole chunk.
        while first - 1 > previous_first and new_start - sentences[first - 1][0] <= overlap:
            first -= 1
        last = first_new
        while last + 1 < len(sentences) and sentences[last + 1][1] - new_start <= size:
            last += 1
        chunks.append((sentences[first][0], sentences[last][1]))
        previous_first = first
        first_new = last + 1
    return chunks


def _paragraphs(text: str, start: int, end: int) -> Iterator[Span]:
    paragraph_start = start
    for match in _PARAGRAPH_BREAK_RE.finditer(text, start, end):
        yield paragraph_start, match.start()
        paragraph_start = match.end()
    yield paragraph_start, end


def _cut(text: str, start: int, end: int, max_chars: int) -> Iterator[Span]:
    """Parts of at most max_chars of text[start:end], which starts and ends with a non-space.

    A part ends before the word the limit falls in, unless that word is the only one.
    """
    while end - start > max_chars:
        part = text[start : start + max_chars]
        if not (part[-1].isspace() or text[start + max_chars].isspace()):
            part = part.rsplit(maxsplit=1)[0]
        part_end = start + len(part.rstrip())
        yield start, part_end
        start = _skip_spaces(text, part_end, end)
    yield start, end


def _skip_spaces(text: str, start: int, end: int) -> int:
    """The position of the first non-space character in text[start:end], or end."""
    match = _NON_SPACE_RE.search(text, start, end)
    return end if match is None else match.start()


def _markdown_sections(text: str) -> Iterator[_Section]:
    """The heading titles above each section that has text, and where its body is.

    The text before the first heading is a section without titles.
    """
    open_headings: list[tuple[int, str]] = []
    body_start = 0
    fence: str | None = None
    for match in _MARKDOWN_LINE_RE.finditer(text):
        line_start = match.start()
        line_end = text.find("\n", line_start)
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end].lstrip(" ")
        if line.startswith(_CODE_FENCES):
            # A fence closes only a block opened by a fence of the same character.
            if fence is None:
                fence = line[0]
            elif line[0] == fence:
                fence = None
            continue
        heading = None if fence is not None else _heading(line)
        if heading is None:
            continue
        if _NON_SPACE_RE.search(text, body_start, line_start):
            yield tuple(title for _, title in open_headings), body_start, line_start
        level, title = heading
        while open_headings and open_headings[-1][0] >= level:
            open_headings.pop()
        if title:
            open_headings.append((level, title))
        body_start = line_end
    if _NON_SPACE_RE.search(text, body_start):
        yield tuple(title for _, title in open_headings), body_start, len(text)


def _heading(line: str) -> tuple[int, str] | None:
    """The level and the title of a heading line such as "## Title ##", else None.

    The line comes without its indentation. Plain string operations rather than a regex
    keep this linear on lines of many "#".
    """
    level = len(line) - len(line.lstrip("#"))
    rest = line[level:]
    if not 1 <= level <= MARKDOWN_MAX_HEADING_LEVEL or rest[:1] not in ("", " ", "\t"):
        return None
    title = rest.strip(" \t")
    # A closing run of "#" counts only after a space, so "C#" keeps its "#".
    without_closing = title.rstrip("#")
    if not without_closing or without_closing[-1] in " \t":
        title = without_closing
    return level, " ".join(title.split())


def _heading_path(titles: Sequence[str]) -> str | None:
    """The titles joined from the outermost one, or None when there are none.

    A path too long for its column loses its leading titles first; a last title too long
    on its own is cut at a word boundary.
    """
    for first in range(len(titles)):
        path = HEADING_SEPARATOR.join(titles[first:])
        if len(path) <= CHUNK_HEADING_MAX_LENGTH:
            return path
    return shorten(titles[-1], CHUNK_HEADING_MAX_LENGTH) if titles else None
