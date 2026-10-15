"""Cleaning of extracted document text before it is checked, chunked and analysed.

Stored text is NFC rather than NFKC, which would turn x² into x2 and H₂O into H2O. Every
step runs on untrusted text, so each one must stay linear on hostile input such as two
million dots.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from typing import Final

from app.documents.errors import TEXT_TOO_LONG_MESSAGE, DocumentProcessingError

# CPython composes a run that grows when it is decomposed, such as U+0958 DEVANAGARI LETTER
# QA or U+212B ANGSTROM SIGN repeated, in time quadratic in its length, so text is composed
# in pieces of at most this many characters.
NFC_PIECE_MAX_CHARS: Final = 4096
# Page numbers are looked for among this many lines at the top and at the bottom of a page.
PAGE_NUMBER_EDGE_LINES: Final = 3
# A line is a running header or footer when it stands at the same edge of at least this
# share of the pages and of at least RUNNING_LINE_MIN_PAGES pages.
RUNNING_LINE_MIN_SHARE: Final = 0.5
RUNNING_LINE_MIN_PAGES: Final = 3
RUNNING_LINES_MAX_PER_EDGE: Final = 3

_SOFT_HYPHEN: Final = "\N{SOFT HYPHEN}"
# Every line break str.splitlines knows, "\r\n" counting as one.
_LINE_BREAK_RE: Final = re.compile(
    r"\r\n?|[\v\f\x1c-\x1e\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]"
)
_NO_BREAK_SPACES: Final = ("\N{NO-BREAK SPACE}", "\N{NARROW NO-BREAK SPACE}")
# Latin ligatures that PDF fonts produce (U+FB00 to U+FB06), spelled out as NFKC does.
_LIGATURES: Final = {
    chr(code): unicodedata.normalize("NFKC", chr(code)) for code in range(0xFB00, 0xFB07)
}
# Control characters other than "\n" and "\t", zero-width spaces and joiners, the word
# joiner, the byte order mark and lone surrogates: a PDF font's map to Unicode can produce
# those, and UTF-8 cannot encode them. In a str every surrogate is a lone one.
_INVISIBLE_RE: Final = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\N{ZERO WIDTH SPACE}-\N{ZERO WIDTH JOINER}"
    r"\N{WORD JOINER}\N{ZERO WIDTH NO-BREAK SPACE}\ud800-\udfff]++"
)
# A soft hyphen shows only where a line breaks at it, and there it shows as a hyphen.
_LINE_END_SOFT_HYPHEN_RE: Final = re.compile(r"\N{SOFT HYPHEN}(?=[^\S\n]*+(?:\n|\Z))")
# The lookbehind lets a match start only where a run of spaces starts, so a long run that
# is not at the end of its line is scanned once rather than once per space.
_TRAILING_SPACE_RE: Final = re.compile(r"(?<![^\S\n])[^\S\n]++$", re.MULTILINE)
# A hyphen after a letter at the end of a line, with the next line starting with a letter.
# Only a lower-case letter continues a broken word: "Москва-" before "Река" stays as it is.
_LINE_END_HYPHEN_RE: Final = re.compile(r"(?<=[^\W\d_])[-\N{HYPHEN}]\n[^\S\n]*+(?=[^\W\d_])")
# A line that is only a page number: "7", "Page 7 of 12", "Стр. 7", "7 / 12", "7 из 12".
_PAGE_NUMBER_RE: Final = re.compile(
    r"(?:(?:page|стр\.?|страница)\s*+)?\d{1,5}+(?:\s*+(?:/|of|из)\s*+\d{1,5}+)?",
    re.IGNORECASE,
)
_DIGITS_RE: Final = re.compile(r"\d++")
_LETTER_OR_DIGIT_RE: Final = re.compile(r"[^\W_]")

_NO_TEXT_MESSAGE: Final = "The document has no text: no letters or digits were found."


def clean_text(text: str) -> str:
    """Uniform line breaks and spaces, spelled-out ligatures, no invisible characters, NFC.

    Lines lose their trailing spaces and the text its leading and trailing blank lines.
    """
    text = _LINE_BREAK_RE.sub("\n", text)
    for space in _NO_BREAK_SPACES:
        text = text.replace(space, " ")
    for ligature, letters in _LIGATURES.items():
        text = text.replace(ligature, letters)
    text = _INVISIBLE_RE.sub("", text)
    text = _LINE_END_SOFT_HYPHEN_RE.sub("-", text).replace(_SOFT_HYPHEN, "")
    return _TRAILING_SPACE_RE.sub("", _compose(text)).strip("\n")


def _compose(text: str) -> str:
    """NFC, a piece at a time.

    A piece ends before a line break or a space, which nothing composes across; failing
    that, before a character of combining class 0; failing that, anywhere. Every cut keeps
    the text canonically equivalent; the fallbacks, needed only in thousands of characters
    without a space, may leave a letter and its marks or a Hangul syllable uncomposed.
    """
    pieces: list[str] = []
    start = 0
    while len(text) - start > NFC_PIECE_MAX_CHARS:
        end = _piece_end(text, start)
        pieces.append(unicodedata.normalize("NFC", text[start:end]))
        start = end
    pieces.append(unicodedata.normalize("NFC", text[start:]))
    return "".join(pieces)


def _piece_end(text: str, start: int) -> int:
    limit = start + NFC_PIECE_MAX_CHARS
    end = max(text.rfind("\n", start + 1, limit + 1), text.rfind(" ", start + 1, limit + 1))
    if end > start:
        return end
    for end in range(limit, start, -1):
        if not unicodedata.combining(text[end]):
            return end
    return limit


def clean_pdf_pages(pages: Sequence[str]) -> list[str]:
    """Clean each page and remove what the page layout added to its text.

    Blank lines, page numbers at the top or the bottom and running headers and footers
    repeated at the edges of the pages are dropped; then words hyphenated at line ends are
    joined, so a word broken at the end of the body never runs into a footer.
    """
    page_lines = [_drop_page_numbers(_page_lines(page)) for page in pages]
    _drop_running_lines(page_lines)
    return [
        _LINE_END_HYPHEN_RE.sub(_join_lower_case_continuation, "\n".join(lines))
        for lines in page_lines
    ]


def _page_lines(page: str) -> list[str]:
    # Cleaning left no trailing spaces, so a blank line is an empty one.
    return [line for line in clean_text(page).split("\n") if line]


def _join_lower_case_continuation(match: re.Match[str]) -> str:
    return "" if match.string[match.end()].islower() else match.group()


def _drop_page_numbers(lines: list[str]) -> list[str]:
    bottom = len(lines) - PAGE_NUMBER_EDGE_LINES
    return [
        line
        for index, line in enumerate(lines)
        if not (
            (index < PAGE_NUMBER_EDGE_LINES or index >= bottom)
            and _PAGE_NUMBER_RE.fullmatch(line.strip())
        )
    ]


def _drop_running_lines(pages: list[list[str]]) -> None:
    """Remove running headers and footers from the pages' lines in place.

    The first or the last line goes while that line, numbers aside, stands at the same edge
    of enough pages; up to RUNNING_LINES_MAX_PER_EDGE lines go at each edge.
    """
    min_pages = max(RUNNING_LINE_MIN_PAGES, math.ceil(len(pages) * RUNNING_LINE_MIN_SHARE))
    for edge in (0, -1):
        for _ in range(RUNNING_LINES_MAX_PER_EDGE):
            keys = [_running_line_key(lines[edge]) if lines else None for lines in pages]
            counts = Counter(key for key in keys if key is not None)
            running = {key for key, count in counts.items() if count >= min_pages}
            if not running:
                break
            for lines, key in zip(pages, keys, strict=True):
                if key in running:
                    del lines[edge]


def _running_line_key(line: str) -> str:
    # Running lines often carry the page number: "Lecture 3, page 12".
    return _DIGITS_RE.sub("#", " ".join(line.split()))


def check_text(text: str, *, max_chars: int) -> None:
    """Reject cleaned text that is too long to process or has no letter or digit at all."""
    if len(text) > max_chars:
        raise DocumentProcessingError("text_too_long", TEXT_TOO_LONG_MESSAGE)
    if _LETTER_OR_DIGIT_RE.search(text) is None:
        raise DocumentProcessingError("no_text", _NO_TEXT_MESSAGE)
