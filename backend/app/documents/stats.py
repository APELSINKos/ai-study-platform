"""Counts shown on a document: how many words it has and how long it takes to study."""

import math
from collections.abc import Mapping
from fractions import Fraction
from typing import Final

from app.documents.text import words as split_words
from app.models.document import Difficulty

READING_WORDS_PER_MINUTE: Final = 200
# How much longer studying takes than reading through once. Fractions keep the product
# exact, so a whole number of minutes is never rounded up by a float error.
STUDY_TIME_FACTORS: Final[Mapping[Difficulty, Fraction]] = {
    "easy": Fraction("1.0"),
    "medium": Fraction("1.3"),
    "hard": Fraction("1.6"),
}
MIN_STUDY_MINUTES: Final = 1


def word_count(text: str) -> int:
    return len(split_words(text))


def estimated_study_minutes(words: int, difficulty: Difficulty) -> int:
    """Reading time at READING_WORDS_PER_MINUTE, longer for harder material, in whole minutes."""
    minutes = Fraction(words, READING_WORDS_PER_MINUTE) * STUDY_TIME_FACTORS[difficulty]
    return max(MIN_STUDY_MINUTES, math.ceil(minutes))
