# ruff: noqa: RUF001 -- Russian sample text and typographic quotes are intended

import time
from typing import Final

import pytest

from app.documents.text import (
    ELLIPSIS,
    STOPWORDS_EN,
    STOPWORDS_RU,
    has_cyrillic,
    shorten,
    split_sentences,
    words,
)

HOSTILE_TEXT_LENGTH: Final = 2_000_000
HOSTILE_UNITS: Final = (".", "!?", "…", "#", " #", "-")
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0


def test_words_are_letters_and_digits_of_any_script() -> None:
    assert words("Привет, world! 42 ёлки, (SQL)") == ["Привет", "world", "42", "ёлки", "SQL"]


def test_a_hyphen_or_apostrophe_between_letters_stays_inside_the_word() -> None:
    assert words("из-за don't rock’n’roll well-known") == [
        "из-за",
        "don't",
        "rock’n’roll",
        "well-known",
    ]


def test_dashes_quotes_and_underscores_around_words_are_not_part_of_them() -> None:
    assert words("-word- 'quoted' «ёж» snake_case — dash -- x") == [
        "word",
        "quoted",
        "ёж",
        "snake",
        "case",
        "dash",
        "x",
    ]


def test_superscripts_and_subscripts_stay_in_their_word() -> None:
    assert words("x² + H₂O") == ["x²", "H₂O"]


def test_text_without_letters_or_digits_has_no_words() -> None:
    assert words(" ... — !? ") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Spaced repetition works. It schedules reviews! Does it help? Yes.",
            ["Spaced repetition works.", "It schedules reviews!", "Does it help?", "Yes."],
        ),
        (
            "Нормализация устраняет избыточность. Первая форма требует атомарности! "
            "Зачем это нужно? Ёмкий ответ ниже.",
            [
                "Нормализация устраняет избыточность.",
                "Первая форма требует атомарности!",
                "Зачем это нужно?",
                "Ёмкий ответ ниже.",
            ],
        ),
        (
            "Wait... What?! The 3rd step.\nThen the 4th.",
            ["Wait...", "What?!", "The 3rd step.", "Then the 4th."],
        ),
        ("Total: 2 items. 3 more later.", ["Total: 2 items.", "3 more later."]),
    ],
    ids=["english", "russian", "punctuation-runs-and-newlines", "digit-starts-a-sentence"],
)
def test_text_is_split_after_terminal_punctuation_before_a_capital_or_digit(
    text: str, expected: list[str]
) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("«Цитата.» Далее идёт текст.", ["«Цитата.»", "Далее идёт текст."]),
        ('He said "Stop." Then he left.', ['He said "Stop."', "Then he left."]),
        ("(See the appendix.) Next part.", ["(See the appendix.)", "Next part."]),
        ("Он ушёл. «Почему?» — спросил я.", ["Он ушёл.", "«Почему?» — спросил я."]),
        ('Она спросила: "Зачем?" Ответа не было.', ['Она спросила: "Зачем?"', "Ответа не было."]),
    ],
    ids=[
        "closing-guillemet",
        "closing-double-quote",
        "closing-bracket",
        "opening-guillemet",
        "question-in-quotes",
    ],
)
def test_quotes_and_brackets_stay_with_their_sentence(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "«Почему?» — спросил он.",
        '"Why?" he asked.',
        "The end. but not really.",
        "Call me at 5 p.m. tomorrow.",
    ],
    ids=[
        "dash-after-a-quote",
        "lower-case-after-a-quote",
        "lower-case",
        "abbreviation-before-lower-case",
    ],
)
def test_a_lower_case_continuation_is_not_a_new_sentence(text: str) -> None:
    assert split_sentences(text) == [text]


@pytest.mark.parametrize(
    "text",
    [
        "The value of pi is 3.14 and e is 2.718 here.",
        "Версия 2.0 вышла 1.10.2026 утром.",
    ],
    ids=["english", "russian-date"],
)
def test_decimals_and_dates_do_not_end_a_sentence(text: str) -> None:
    assert split_sentences(text) == [text]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Роман «Дубровский» написал А. С. Пушкин. Он жил в Москве.",
            ["Роман «Дубровский» написал А. С. Пушкин.", "Он жил в Москве."],
        ),
        (
            "The book is by J. R. R. Tolkien. It is long.",
            ["The book is by J. R. R. Tolkien.", "It is long."],
        ),
    ],
    ids=["russian", "english"],
)
def test_initials_do_not_end_a_sentence(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ask Dr. Watson about it. He knows.", ["Ask Dr. Watson about it.", "He knows."]),
        (
            "Pick a language, e.g. Python or Kotlin. Both work.",
            ["Pick a language, e.g. Python or Kotlin.", "Both work."],
        ),
        (
            "Pick one, i.e. The first option. Done.",
            ["Pick one, i.e. The first option.", "Done."],
        ),
        (
            "Ключ уникален, т. е. СУБД не допустит дубликатов. Это важно.",
            ["Ключ уникален, т. е. СУБД не допустит дубликатов.", "Это важно."],
        ),
        (
            "Ключ уникален, т.е. СУБД не допустит дубликатов. Это важно.",
            ["Ключ уникален, т.е. СУБД не допустит дубликатов.", "Это важно."],
        ),
        (
            "Схема показана на рис. 2 выше. См. Таблицу 3.",
            ["Схема показана на рис. 2 выше.", "См. Таблицу 3."],
        ),
        (
            "The result is shown in Fig. 4 and Eq. 2 below. Next.",
            ["The result is shown in Fig. 4 and Eq. 2 below.", "Next."],
        ),
        (
            "Москва основана в 1147 г. Юрием Долгоруким. Это известно.",
            ["Москва основана в 1147 г. Юрием Долгоруким.", "Это известно."],
        ),
    ],
    ids=["dr", "e.g.", "i.e.", "т. е.", "т.е.", "рис.", "fig.-and-eq.", "single-letter-г."],
)
def test_abbreviations_do_not_end_a_sentence(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Есть яблоки, груши и т. д. Далее идут овощи.",
            ["Есть яблоки, груши и т. д.", "Далее идут овощи."],
        ),
        (
            "Есть яблоки, груши и т.п. Далее идут овощи.",
            ["Есть яблоки, груши и т.п.", "Далее идут овощи."],
        ),
        (
            "We sell apples, pears, etc. Then come vegetables.",
            ["We sell apples, pears, etc.", "Then come vegetables."],
        ),
    ],
    ids=["т. д.", "т.п.", "etc."],
)
def test_an_abbreviation_that_closes_a_list_can_end_a_sentence(
    text: str, expected: list[str]
) -> None:
    assert split_sentences(text) == expected


def test_a_single_letter_before_other_punctuation_ends_a_sentence() -> None:
    assert split_sentences("Is the answer A? B is wrong.") == ["Is the answer A?", "B is wrong."]


@pytest.mark.parametrize("text", ["", "   \n\t  "])
def test_blank_text_has_no_sentences(text: str) -> None:
    assert split_sentences(text) == []


def test_text_without_terminal_punctuation_is_one_sentence() -> None:
    assert split_sentences("  a fragment without an end\n") == ["a fragment without an end"]


def test_cyrillic_is_detected_in_any_case() -> None:
    assert has_cyrillic("hello мир")
    assert has_cyrillic("Ёж")
    assert not has_cyrillic("hello world 42")
    assert not has_cyrillic("")


def test_stopwords_cover_common_function_words() -> None:
    assert {"the", "and", "of", "is", "don't"} <= STOPWORDS_EN
    assert {"и", "в", "не", "что", "это", "который"} <= STOPWORDS_RU
    assert not {"database", "interval", "repetition"} & STOPWORDS_EN
    assert not {"нормализация", "данных", "интервал"} & STOPWORDS_RU


def test_stopwords_are_lower_case_with_yo_written_as_ye() -> None:
    for stopword in STOPWORDS_EN | STOPWORDS_RU:
        assert stopword == stopword.casefold()
        assert "ё" not in stopword
    assert {"ее", "еще", "все"} <= STOPWORDS_RU


def test_short_text_is_not_shortened() -> None:
    assert shorten("Interval repetition", 19) == "Interval repetition"


def test_long_text_is_cut_at_a_word_boundary_with_an_ellipsis() -> None:
    assert shorten("Spaced repetition schedules each review", 25) == "Spaced repetition" + ELLIPSIS


@pytest.mark.parametrize("max_chars", [18, 19], ids=["before-the-space", "after-the-space"])
def test_a_cut_next_to_a_space_keeps_the_whole_word_before_it(max_chars: int) -> None:
    assert shorten("Spaced repetition schedules", max_chars) == "Spaced repetition" + ELLIPSIS


def test_separators_before_the_ellipsis_are_dropped() -> None:
    assert shorten("Нормализация, формы — и аномалии", 23) == "Нормализация, формы" + ELLIPSIS


def test_a_single_long_word_is_cut_hard() -> None:
    assert shorten("Донауфдампфшиффахртсгезельшафт", 10) == "Донауфдам" + ELLIPSIS


@pytest.mark.parametrize("max_chars", [1, 2, 7, 60, 200])
def test_shortened_text_never_exceeds_the_limit(max_chars: int) -> None:
    text = "word " * 100 + "x" * 300

    assert len(shorten(text, max_chars)) <= max_chars


@pytest.mark.parametrize("unit", HOSTILE_UNITS)
def test_long_runs_of_punctuation_and_markup_are_processed_in_linear_time(unit: str) -> None:
    text = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    split_sentences(text)
    words(text)
    shorten(text, 1000)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
