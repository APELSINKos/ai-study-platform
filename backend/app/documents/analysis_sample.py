"""What a document analysis is shown of a document too long to be shown whole.

The beginning of a document says the most about it, so it takes most of the room; three
windows further on show how it goes on and how it ends.
"""

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from typing import Final

from app.documents.chunking import sentence_spans
from app.documents.text import EXCERPT_SEPARATOR

OUTLINE_MAX_CHARS: Final = 1500
# The outline's share of a smaller limit, the same 1500 characters at the default 12,000,
# so that a small limit still leaves most of its room to the text.
OUTLINE_MAX_SHARE: Final = 0.125
# The beginning's share of the room left for excerpts; the windows split the rest equally.
HEAD_SHARE: Final = 0.7
# Where the windows after the beginning are centred, as fractions of the text's length.
WINDOW_CENTRES: Final = (0.4, 0.65, 0.9)
# Excerpts that follow on from each other are joined by the line breaks between them, up
# to a blank line, which ends a paragraph.
JOIN_MAX_LINE_BREAKS: Final = 2


def build_analysis_sample(text: str, headings: Iterable[str], max_chars: int) -> tuple[str, str]:
    """The outline and the sample of a document, together at most max_chars long.

    A document that fits is sent whole, without an outline. A longer one gets an outline
    of its distinct headings and a sample of its beginning and of three windows around 40,
    65 and 90 % of the way through: whole sentences, with EXCERPT_SEPARATOR wherever text
    is left out between them.
    """
    if len(text) <= max_chars:
        return "", text
    outline = _outline(headings, min(OUTLINE_MAX_CHARS, int(max_chars * OUTLINE_MAX_SHARE)))
    room = max_chars - len(outline)
    window_chars = int(
        (room - len(WINDOW_CENTRES) * len(EXCERPT_SEPARATOR))
        * (1 - HEAD_SHARE)
        / len(WINDOW_CENTRES)
    )
    if window_chars < 1:
        # Too little room for the windows and their separators: the beginning alone.
        return outline, _excerpts(text, [(0, room)])
    head_chars = room - len(WINDOW_CENTRES) * (len(EXCERPT_SEPARATOR) + window_chars)
    windows = [
        (int(len(text) * centre) - window_chars // 2, window_chars) for centre in WINDOW_CENTRES
    ]
    return outline, _excerpts(text, [(0, head_chars), *windows])


def _outline(headings: Iterable[str], max_chars: int) -> str:
    """Each heading once, in order and one to a line, as many whole lines as fit."""
    lines: list[str] = []
    length = 0
    for heading in dict.fromkeys(headings):
        added = len(heading) + (1 if lines else 0)
        if length + added > max_chars:
            break
        lines.append(heading)
        length += added
    return "\n".join(lines)


def _excerpts(text: str, regions: Sequence[tuple[int, int]]) -> str:
    """Whole sentences from each region's start, up to its size, joined by the separator.

    An excerpt goes on after the one before it rather than repeat any of its sentences,
    and one that starts at the very next sentence is added to the one before it, as no
    text between them is left out. Sentences longer than the smallest size come in parts,
    so every excerpt gets text.
    """
    spans = sentence_spans(text, 0, len(text), max_chars=min(size for _, size in regions))
    excerpts: list[str] = []
    next_span = 0
    for start, size in regions:
        first = max(next_span, bisect_left(spans, start, key=lambda span: span[0]))
        if first == len(spans):
            break
        last = first
        while last + 1 < len(spans) and spans[last + 1][1] - spans[first][0] <= size:
            last += 1
        excerpt = text[spans[first][0] : spans[last][1]]
        if excerpts and first == next_span:
            excerpts[-1] += _join(text[spans[first - 1][1] : spans[first][0]]) + excerpt
        else:
            excerpts.append(excerpt)
        next_span = last + 1
    return EXCERPT_SEPARATOR.join(excerpts)


def _join(gap: str) -> str:
    """What joins two neighbouring sentences in place of the spaces between them.

    Their line breaks up to a blank line, else their first space, if any: shorter than the
    separator it replaces, so the sample still fits in its limit.
    """
    return "\n" * min(gap.count("\n"), JOIN_MAX_LINE_BREAKS) or gap[:1]
