# ruff: noqa: RUF001 -- Russian sample text is intended

import time
from typing import Final

import pytest

from app.documents.stats import estimated_study_minutes, word_count
from app.models.document import DIFFICULTIES, Difficulty

HOSTILE_TEXT_LENGTH: Final = 2_000_000
HOSTILE_UNITS: Final = (".", "!?", "…", "#", " #", "-")
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0


def test_words_of_any_script_and_numbers_are_counted() -> None:
    assert word_count("Нормализация данных, part 2: ёлки и SQL!") == 7


def test_a_hyphenated_word_counts_once() -> None:
    assert word_count("из-за well-known rock’n’roll") == 3


@pytest.mark.parametrize("text", ["", "  \n\t ", "... — !? «» -- **"])
def test_text_without_letters_or_digits_has_no_words(text: str) -> None:
    assert word_count(text) == 0


@pytest.mark.parametrize(
    ("words", "difficulty", "minutes"),
    [
        (200, "easy", 1),
        (201, "easy", 2),
        (400, "easy", 2),
        (200, "medium", 2),
        (1000, "medium", 7),
        (2000, "medium", 13),
        (6000, "medium", 39),
        (125, "hard", 1),
        (250, "hard", 2),
        (2000, "hard", 16),
    ],
)
def test_study_time_is_reading_time_at_200_words_a_minute_scaled_by_difficulty(
    words: int, difficulty: Difficulty, minutes: int
) -> None:
    assert estimated_study_minutes(words, difficulty) == minutes


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
@pytest.mark.parametrize("words", [0, 1])
def test_study_time_is_at_least_one_minute(words: int, difficulty: Difficulty) -> None:
    assert estimated_study_minutes(words, difficulty) == 1


def test_harder_material_takes_longer_to_study() -> None:
    easy, medium, hard = (estimated_study_minutes(10_000, level) for level in DIFFICULTIES)

    assert (easy, medium, hard) == (50, 65, 80)


@pytest.mark.parametrize("unit", HOSTILE_UNITS)
def test_words_of_long_runs_are_counted_in_linear_time(unit: str) -> None:
    text = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    word_count(text)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
