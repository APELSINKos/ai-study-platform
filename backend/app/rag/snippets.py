"""Snippets: the passages of a chunk that ts_headline picks, as plain and highlighted parts.

The headline comes with marks in its text (see vector_store): the words that the query
matched stand between HIGHLIGHT_START and HIGHLIGHT_STOP, and FRAGMENT_DELIMITER stands
between two passages. The API returns parts, never markup, and the client shows them as text.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from app.documents.text import ELLIPSIS
from app.rag.vector_store import FRAGMENT_DELIMITER, HIGHLIGHT_START, HIGHLIGHT_STOP
from app.schemas.search import SnippetPart

# Two passages of up to 24 words fit with room to spare; only very long words need more.
MAX_SNIPPET_CHARS: Final = 600
_PASSAGE_BREAK: Final = f" {ELLIPSIS} "
# One mark at a time; re.split keeps each mark between the texts before and after it.
_MARK_RE: Final = re.compile(f"([{HIGHLIGHT_START}{HIGHLIGHT_STOP}{FRAGMENT_DELIMITER}])")


@dataclass(frozen=True, slots=True)
class _Word:
    # What stands before the word: nothing, a space or a passage break.
    gap: str
    text: str
    highlighted: bool

    @property
    def length(self) -> int:
        return len(self.gap) + len(self.text)


# Ends a snippet that had to be cut.
_CUT_MARK: Final = _Word(" ", ELLIPSIS, highlighted=False)


def parse_headline(raw: str) -> list[SnippetPart]:
    """The parts of a headline: the words that the query matched highlighted, the rest plain.

    Every run of whitespace becomes one space, passages are joined by an ellipsis, and a
    mark without its partner is dropped. A snippet longer than MAX_SNIPPET_CHARS is cut
    before the first word that does not fit and ends with an ellipsis.
    """
    words: list[_Word] = []
    length = 0
    for word in _words(raw):
        words.append(word)
        length += word.length
        if length > MAX_SNIPPET_CHARS:
            # The snippet has to be cut, so the rest of the headline is not read.
            return _parts(_cut(words))
    return _parts(words)


def _words(raw: str) -> Iterator[_Word]:
    """The words of a headline in reading order, each with the gap before it.

    A text is highlighted when a HIGHLIGHT_START stands right before it and a HIGHLIGHT_STOP
    right after it. Other starts and stops leave no trace.
    """
    # Texts and marks alternate, with a text first and last: text, mark, text, ..., text.
    pieces = _MARK_RE.split(raw)
    texts, marks = pieces[::2], pieces[1::2]
    gap = ""
    first = True
    for before, text, after in zip(["", *marks], texts, [*marks, ""], strict=True):
        if before == FRAGMENT_DELIMITER:
            gap = _PASSAGE_BREAK
        if not text:
            continue
        # A passage break outweighs a space.
        if text[0].isspace() and not gap:
            gap = " "
        highlighted = before == HIGHLIGHT_START and after == HIGHLIGHT_STOP
        for word in text.split():
            yield _Word("" if first else gap, word, highlighted)
            first = False
            gap = " "
        if not text[-1].isspace():
            gap = ""


def _cut(words: list[_Word]) -> list[_Word]:
    """The words that fit within MAX_SNIPPET_CHARS together with the cut mark, then the mark."""
    room = MAX_SNIPPET_CHARS - _CUT_MARK.length
    kept: list[_Word] = []
    length = 0
    for word in words:
        length += word.length
        if length > room:
            break
        kept.append(word)
    if not kept:
        # A first word longer than the snippet is cut through rather than dropped.
        first = words[0]
        kept.append(_Word("", first.text[:room], first.highlighted))
    return [*kept, _CUT_MARK]


def _parts(words: list[_Word]) -> list[SnippetPart]:
    """The words as parts: gaps are plain, and neighbours of the same kind make one part."""
    texts: list[str] = []
    highlights: list[bool] = []
    for word in words:
        for text, highlighted in ((word.gap, False), (word.text, word.highlighted)):
            if not text:
                continue
            if highlights and highlights[-1] == highlighted:
                texts[-1] += text
            else:
                texts.append(text)
                highlights.append(highlighted)
    return [
        SnippetPart(text=text, highlighted=highlighted)
        for text, highlighted in zip(texts, highlights, strict=True)
    ]
