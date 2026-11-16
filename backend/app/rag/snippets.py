"""Snippets: the passages of a chunk that ts_headline picks, as plain and highlighted parts.

The headline comes with marks in its text (see vector_store): the words that the query
matched stand between HIGHLIGHT_START and HIGHLIGHT_STOP, and FRAGMENT_DELIMITER stands
between two passages. The API returns parts, never markup, and the client shows them as text.
An ellipsis stands wherever a snippet leaves out part of its chunk.
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
# The opening of a chunk found by embeddings alone, about as long as a passage of a headline.
OPENING_WORDS: Final = 30
_PASSAGE_BREAK: Final = f" {ELLIPSIS} "
# One mark at a time; re.split keeps each mark between the texts before and after it.
_MARK_RE: Final = re.compile(f"([{HIGHLIGHT_START}{HIGHLIGHT_STOP}{FRAGMENT_DELIMITER}])")
_UNMARK: Final = str.maketrans("", "", HIGHLIGHT_START + HIGHLIGHT_STOP)


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


def snippet_parts(headline: str, content: str) -> list[SnippetPart]:
    """The snippet of a chunk: its headline, with an ellipsis where it leaves the chunk's text out.

    A headline without highlighted words belongs to a chunk found by embeddings alone, for
    which PostgreSQL picks only the first few words: the chunk's first OPENING_WORDS words
    stand in. A snippet holds at most MAX_SNIPPET_CHARS characters after its first ellipsis.
    """
    words = _headline_words(headline)
    if not any(word.highlighted for word in words):
        return _parts(_opening(content))
    if words[-1] != _CUT_MARK and not _reaches_end(headline, content):
        words.append(_CUT_MARK)
    if not _starts_at_beginning(headline, content):
        first = words[0]
        words[0] = _Word(" ", first.text, first.highlighted)
        words.insert(0, _Word("", ELLIPSIS, highlighted=False))
    return _parts(words)


def parse_headline(raw: str) -> list[SnippetPart]:
    """The parts of a headline: the words that the query matched highlighted, the rest plain.

    Every run of whitespace becomes one space, passages are joined by an ellipsis, and a
    mark without its partner is dropped. A snippet longer than MAX_SNIPPET_CHARS ends with
    an ellipsis, cut before the first word (a run between spaces or marks) that does not fit.
    """
    return _parts(_headline_words(raw))


def _headline_words(raw: str) -> list[_Word]:
    """The words of a headline, cut with an ellipsis if they do not fit MAX_SNIPPET_CHARS."""
    words: list[_Word] = []
    length = 0
    for word in _words(raw):
        words.append(word)
        length += word.length
        if length > MAX_SNIPPET_CHARS:
            # The snippet has to be cut, so the rest of the headline is not turned into words.
            return _cut(words)
    return words


def _opening(content: str) -> list[_Word]:
    """The first OPENING_WORDS words of a chunk, then an ellipsis when more follow."""
    pieces = content.split(maxsplit=OPENING_WORDS)
    words = _headline_words(" ".join(pieces[:OPENING_WORDS]))
    if len(pieces) > OPENING_WORDS and words[-1] != _CUT_MARK:
        words.append(_CUT_MARK)
    return words


# The headline leaves out the punctuation before a chunk's first word and after its last, so
# only letters and digits decide whether a passage reaches the start or the end of the chunk.


def _starts_at_beginning(headline: str, content: str) -> bool:
    """Whether the headline's first passage starts where its chunk does."""
    first = headline.split(FRAGMENT_DELIMITER, 1)[0].translate(_UNMARK)
    first = first[_first_word_index(first) :]
    return content.startswith(first, _first_word_index(content))


def _reaches_end(headline: str, content: str) -> bool:
    """Whether the headline's last passage ends where its chunk does."""
    last = headline.rsplit(FRAGMENT_DELIMITER, 1)[-1].translate(_UNMARK)
    last = last[: _last_word_end(last)]
    return content.endswith(last, 0, _last_word_end(content))


def _first_word_index(text: str) -> int:
    """Where the first letter or digit of a text stands; the text's length when it has none."""
    for index, character in enumerate(text):
        if character.isalnum():
            return index
    return len(text)


def _last_word_end(text: str) -> int:
    """Where a text ends once what follows its last letter or digit is left out."""
    for index in range(len(text), 0, -1):
        if text[index - 1].isalnum():
            return index
    return 0


def _words(raw: str) -> Iterator[_Word]:
    """The words of a headline in reading order, each with the gap before it.

    A text is highlighted when a HIGHLIGHT_START stands right before it and a HIGHLIGHT_STOP
    right after it. Other starts and stops leave no trace.
    """
    # Texts and marks alternate, with a text first and last: text, mark, text, ..., text.
    # So the texts stand at even indexes, each between the marks before and after it.
    pieces = _MARK_RE.split(raw)
    gap = ""
    first = True
    for index in range(0, len(pieces), 2):
        before = pieces[index - 1] if index > 0 else ""
        text = pieces[index]
        after = pieces[index + 1] if index + 1 < len(pieces) else ""
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
    parts: list[SnippetPart] = []
    for word in words:
        for text, highlighted in ((word.gap, False), (word.text, word.highlighted)):
            if not text:
                continue
            if parts and parts[-1].highlighted == highlighted:
                parts[-1].text += text
            else:
                parts.append(SnippetPart(text=text, highlighted=highlighted))
    return parts
