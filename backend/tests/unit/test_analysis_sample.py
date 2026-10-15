import re
import time
from typing import Final

import pytest

from app.documents.analysis_sample import (
    HEAD_SHARE,
    OUTLINE_MAX_CHARS,
    WINDOW_CENTRES,
    build_analysis_sample,
)
from app.documents.text import EXCERPT_SEPARATOR

MAX_CHARS: Final = 12_000
SENTENCE_COUNT: Final = 1000
# Every sentence is the same length and carries its own number.
SENTENCES: Final = [
    f"Sentence {index:04d} explains one more idea about databases."
    for index in range(SENTENCE_COUNT)
]
LONG_TEXT: Final = " ".join(SENTENCES)
HEADINGS: Final = [f"Heading number {index:03d}" for index in range(200)]
HOSTILE_TEXT_LENGTH: Final = 2_000_000
HOSTILE_UNITS: Final = (".", "!?", "…", "#", " #", "-")
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0
_NUMBER_RE: Final = re.compile(r"Sentence (\d{4})")


def _numbers(text: str) -> list[int]:
    return [int(number) for number in _NUMBER_RE.findall(text)]


def _excerpts(sample: str) -> list[str]:
    return sample.split(EXCERPT_SEPARATOR)


@pytest.mark.parametrize("length", [100, MAX_CHARS], ids=["short", "exactly-the-limit"])
def test_a_document_that_fits_is_sent_whole_without_an_outline(length: int) -> None:
    text = ("Spaced repetition works.\n\n" * MAX_CHARS)[:length]

    assert build_analysis_sample(text, HEADINGS, MAX_CHARS) == ("", text)


@pytest.mark.parametrize("max_chars", [500, 2000, MAX_CHARS, 30_000])
def test_outline_and_sample_together_fit_in_the_limit(max_chars: int) -> None:
    outline, sample = build_analysis_sample(LONG_TEXT, HEADINGS, max_chars)

    assert outline
    assert sample
    assert len(outline) + len(sample) <= max_chars


def test_the_sample_is_the_beginning_and_three_windows_joined_by_the_separator() -> None:
    _, sample = build_analysis_sample(LONG_TEXT, [], MAX_CHARS)

    excerpts = _excerpts(sample)

    assert len(excerpts) == 1 + len(WINDOW_CENTRES)
    assert _numbers(excerpts[0])[0] == 0


def test_every_excerpt_is_a_run_of_whole_sentences() -> None:
    _, sample = build_analysis_sample(LONG_TEXT, [], MAX_CHARS)

    for excerpt in _excerpts(sample):
        numbers = _numbers(excerpt)
        assert excerpt == " ".join(SENTENCES[numbers[0] : numbers[-1] + 1])


def test_the_beginning_takes_most_of_the_room() -> None:
    _, sample = build_analysis_sample(LONG_TEXT, [], MAX_CHARS)

    head, *windows = _excerpts(sample)

    share = len(head) / (len(head) + sum(len(window) for window in windows))
    assert HEAD_SHARE == 0.7
    assert share == pytest.approx(HEAD_SHARE, abs=0.02)
    assert len(sample) > MAX_CHARS - 2 * len(SENTENCES[0])


def test_the_windows_are_centred_at_40_65_and_90_percent_of_the_text() -> None:
    _, sample = build_analysis_sample(LONG_TEXT, [], MAX_CHARS)

    _, *windows = _excerpts(sample)

    assert WINDOW_CENTRES == (0.4, 0.65, 0.9)
    for window, centre in zip(windows, WINDOW_CENTRES, strict=True):
        numbers = _numbers(window)
        middle = (numbers[0] + numbers[-1] + 1) / 2 / SENTENCE_COUNT
        assert middle == pytest.approx(centre, abs=0.01)


def test_excerpts_keep_the_order_of_the_text_and_never_repeat_a_sentence() -> None:
    # Just over the limit, so the windows at 40 and 65 % would overlap the beginning.
    text = " ".join(SENTENCES[:240])

    _, sample = build_analysis_sample(text, [], MAX_CHARS)

    numbers = _numbers(sample)
    assert numbers == sorted(set(numbers))
    assert len(_excerpts(sample)) > 1


@pytest.mark.parametrize("gap", [" ", "\n", "\n\n"], ids=["space", "line-break", "blank-line"])
@pytest.mark.parametrize("length", [MAX_CHARS + 1, 15_000, 20_000, 30_000])
def test_the_separator_stands_only_where_text_is_left_out(gap: str, length: int) -> None:
    text = gap.join(SENTENCES)[:length]

    outline, sample = build_analysis_sample(text, [], MAX_CHARS)

    # Excerpts that follow on from each other are joined by their own spaces, so each one
    # is found in the text as it is.
    end = 0
    for index, excerpt in enumerate(_excerpts(sample)):
        start = text.index(excerpt, end)
        assert index == 0 or text[end:start].strip()
        end = start + len(excerpt)
    assert len(outline) + len(sample) <= MAX_CHARS


def test_parts_of_a_run_without_spaces_that_follow_on_are_joined_as_they_are() -> None:
    text = "x" * (MAX_CHARS + 1)

    _, sample = build_analysis_sample(text, [], MAX_CHARS)

    assert sample
    assert text.startswith(sample)


def test_the_outline_lists_each_heading_once_in_order() -> None:
    headings = ["Keys", "Normal forms", "Keys", "Transactions", "Normal forms"]

    outline, _ = build_analysis_sample(LONG_TEXT, headings, MAX_CHARS)

    assert outline == "Keys\nNormal forms\nTransactions"


def test_the_outline_keeps_as_many_whole_headings_as_fit() -> None:
    outline, _ = build_analysis_sample(LONG_TEXT, HEADINGS, MAX_CHARS)

    lines = outline.split("\n")
    assert lines == HEADINGS[: len(lines)]
    assert OUTLINE_MAX_CHARS == 1500
    assert OUTLINE_MAX_CHARS - len(HEADINGS[0]) - 1 < len(outline) <= OUTLINE_MAX_CHARS


def test_a_text_without_sentence_ends_or_spaces_is_still_sampled() -> None:
    text = "x" * 50_000

    _, sample = build_analysis_sample(text, [], MAX_CHARS)

    assert len(_excerpts(sample)) == 1 + len(WINDOW_CENTRES)
    assert set(sample.replace(EXCERPT_SEPARATOR, "")) == {"x"}
    assert MAX_CHARS - 10 < len(sample) <= MAX_CHARS


@pytest.mark.parametrize("max_chars", [1, 10, 25, 40, 100])
def test_a_tiny_limit_still_gives_a_bounded_sample_of_the_beginning(max_chars: int) -> None:
    outline, sample = build_analysis_sample(LONG_TEXT, HEADINGS, max_chars)

    assert sample
    assert LONG_TEXT.startswith(_excerpts(sample)[0])
    assert len(outline) + len(sample) <= max_chars


@pytest.mark.parametrize("unit", HOSTILE_UNITS)
def test_long_runs_are_sampled_in_linear_time(unit: str) -> None:
    text = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    outline, sample = build_analysis_sample(text, HEADINGS, MAX_CHARS)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
    assert len(outline) + len(sample) <= MAX_CHARS
