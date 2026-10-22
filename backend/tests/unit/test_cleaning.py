# ruff: noqa: RUF001 -- Russian sample text is intended

import contextlib
import string
import time
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

from app.documents.cleaning import (
    WRAPPED_LINE_MIN_CHARS,
    check_text,
    clean_pdf_pages,
    clean_text,
)
from app.documents.errors import DocumentProcessingError
from app.documents.extraction import extract
from tests.fixtures.pdf_builder import mapped_text_pdf, text_pdf

LECTURE_PDF: Final = Path(__file__).resolve().parents[1] / "fixtures" / "lecture-ru.pdf"
LECTURE_HEADER: Final = "Базы данных — конспект лекций"
HOSTILE_TEXT_LENGTH: Final = 2_000_000
HOSTILE_UNITS: Final = (".", "!?", "…", "#", " #", "-")
# Runs that grow when decomposed: U+00E9 before a combining acute accent, U+0958 DEVANAGARI
# LETTER QA and U+212B ANGSTROM SIGN. CPython composes a whole run like that in quadratic time.
EXPANDING_UNITS: Final = (
    "\xe9\N{COMBINING ACUTE ACCENT}",
    "\N{DEVANAGARI LETTER QA}",
    "\N{ANGSTROM SIGN}",
)
# Combining marks with no letter in sight, so a piece has nowhere good to end.
MARK_UNITS: Final = ("\N{COMBINING ACUTE ACCENT}",)
# Line structure the cleaning looks at: breaks, soft hyphens, trailing spaces, hyphenation,
# short lines and lines long enough to have been wrapped.
LINE_UNITS: Final = ("\r\n", "\xad", " \n", "a-\n", "a\n", "a" * WRAPPED_LINE_MIN_CHARS + "\n")
# Many short pages, on which a cost that grows page after page shows.
HOSTILE_PAGE_LENGTH: Final = 100
# Timed with coverage's tracer paused (no_cover): tracing multiplies the time of every step.
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0


@pytest.mark.parametrize(
    "text",
    ["x² + y³ = z²", "H₂O и CO₂", "½ стакана, ¾ часа", "10 км² и 5 м³"],
    ids=["superscripts", "subscripts", "fractions", "units"],
)
def test_superscripts_subscripts_and_fractions_are_kept(text: str) -> None:
    assert clean_text(text) == text


def test_letters_written_with_combining_marks_are_composed() -> None:
    composed = "Ёлка, йод и café"

    assert clean_text(unicodedata.normalize("NFD", composed)) == composed


def test_latin_ligatures_are_spelled_out() -> None:
    text = (
        "\N{LATIN SMALL LIGATURE FI}rst \N{LATIN SMALL LIGATURE FL}ow "
        "e\N{LATIN SMALL LIGATURE FFI}cient o\N{LATIN SMALL LIGATURE FF} "
        "ba\N{LATIN SMALL LIGATURE FFL}e \N{LATIN SMALL LIGATURE ST}ory "
        "\N{LATIN SMALL LIGATURE LONG S T}"
    )

    assert clean_text(text) == "first flow efficient off baffle story st"


def test_no_break_spaces_become_ordinary_spaces() -> None:
    text = "10\N{NO-BREAK SPACE}kg и\N{NARROW NO-BREAK SPACE}так далее"

    assert clean_text(text) == "10 kg и так далее"


def test_soft_hyphens_inside_words_are_removed() -> None:
    assert clean_text("инфор\xadмация и норма\xad\xadлизация") == "информация и нормализация"


def test_a_soft_hyphen_where_a_line_breaks_shows_as_a_hyphen() -> None:
    assert clean_text("инфор\xad \nмация") == "инфор-\nмация"


def test_zero_width_characters_and_byte_order_marks_are_removed() -> None:
    text = (
        "\N{BYTE ORDER MARK}zero\N{ZERO WIDTH SPACE}width\N{ZERO WIDTH NON-JOINER}"
        "\N{ZERO WIDTH JOINER}\N{WORD JOINER} text\N{BYTE ORDER MARK}"
    )

    assert clean_text(text) == "zerowidth text"


def test_control_characters_are_removed_except_line_breaks_and_tabs() -> None:
    assert clean_text("a\x00b\x07c\td\x1be\x7ff\x9fg\nh") == "abc\tdefg\nh"


def test_lone_surrogates_are_removed_and_other_characters_kept() -> None:
    # UTF-8, and so the database, cannot encode a lone surrogate.
    assert (
        clean_text("a\ud800b\udfffc = \U0001d465\N{GRINNING FACE}")
        == "abc = \U0001d465\N{GRINNING FACE}"
    )


def test_every_kind_of_line_break_becomes_a_newline() -> None:
    text = "a\r\nb\rc\x0bd\x0ce\x1cf\x1dg\x1eh\x85i\N{LINE SEPARATOR}j\N{PARAGRAPH SEPARATOR}k"

    assert clean_text(text) == "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk"


def test_trailing_spaces_and_blank_lines_at_the_edges_are_removed() -> None:
    text = (
        "\r\n\n  Indented title \t\n"
        "body\N{NO-BREAK SPACE}\N{IDEOGRAPHIC SPACE}\n\n\n"
        "next paragraph  \n \n"
    )

    assert clean_text(text) == "  Indented title\nbody\n\n\nnext paragraph"


def test_markdown_structure_survives_cleaning() -> None:
    text = "# Normal forms\n\n    SELECT *\n\tFROM t;\n\n- first\n- second\n> quote"

    assert clean_text(text) == text


def test_a_hyphen_ending_a_line_of_a_text_file_is_kept() -> None:
    assert clean_text("инфор-\nмация") == "инфор-\nмация"


def test_a_long_line_without_spaces_is_composed_as_a_whole() -> None:
    # Every second character is a combining mark, so a cut at an arbitrary place could
    # separate one from its letter.
    text = "x" + "e\N{COMBINING ACUTE ACCENT}" * 5000

    assert clean_text(text) == "x" + "\xe9" * 5000


def test_long_text_is_composed_the_same_as_in_one_piece() -> None:
    text = unicodedata.normalize("NFD", "Ёлка и йод в каждой строке. " * 2000)

    assert clean_text(text) == unicodedata.normalize("NFC", text).rstrip()


def test_long_decomposed_korean_is_composed_the_same_as_in_one_piece() -> None:
    # Hangul vowels and final consonants compose with the letter before them although
    # their combining class is 0, so only a cut at a space is safe inside such text.
    text = unicodedata.normalize("NFD", "한국어 문장을 읽습니다 " * 1000)

    assert clean_text(text) == unicodedata.normalize("NFC", text).rstrip()


def test_a_long_run_of_combining_marks_stays_canonically_equivalent() -> None:
    text = "a" + "\N{COMBINING ACUTE ACCENT}\N{COMBINING DOT BELOW}" * 5000

    assert unicodedata.normalize("NFD", clean_text(text)) == unicodedata.normalize("NFD", text)


def _pdf_pages(path: Path) -> list[str]:
    extracted = extract(
        path,
        "application/pdf",
        max_pdf_pages=500,
        max_chars=2_000_000,
        check_deadline=lambda: None,
    )
    assert extracted.pages is not None
    return extracted.pages


def _built_pdf_pages(tmp_path: Path, pages: Sequence[Sequence[str]]) -> list[str]:
    path = tmp_path / "notes.pdf"
    path.write_bytes(text_pdf(pages))
    return _pdf_pages(path)


def test_a_lone_surrogate_from_the_font_map_of_a_pdf_is_removed(tmp_path: Path) -> None:
    path = tmp_path / "mapped.pdf"
    path.write_bytes(mapped_text_pdf(b"AAB AA", {0x41: "0041", 0x42: "D800"}))
    pages = _pdf_pages(path)
    # The PDF library hands the surrogate over as it is.
    assert [page.strip() for page in pages] == ["AA\ud800 AA"]

    cleaned = clean_pdf_pages(pages)

    assert cleaned == ["AA AA"]


def test_a_word_hyphenated_at_a_line_end_is_joined() -> None:
    page = "Это инфор-\nмация о нормали-\n  зации."

    assert clean_pdf_pages([page]) == ["Это информация о нормализации."]


def test_a_word_broken_before_a_page_number_is_not_joined_to_it() -> None:
    assert clean_pdf_pages(["Текст про инфор-\nстр. 2"]) == ["Текст про инфор-"]


def test_a_word_broken_before_a_running_footer_is_not_joined_to_it() -> None:
    # The footer goes from every page, the one after the broken word included.
    pages = [
        "Это важная инфор-\nwww.example.ru",
        "Вторая страница.\nwww.example.ru",
        "Третья страница.\nwww.example.ru",
        "Четвёртая страница.\nwww.example.ru",
    ]

    assert clean_pdf_pages(pages) == [
        "Это важная инфор-",
        "Вторая страница.",
        "Третья страница.",
        "Четвёртая страница.",
    ]


def test_a_word_hyphenated_at_the_end_of_a_page_is_joined_on_the_page_where_it_starts() -> None:
    # The running header and the page numbers go first, so the word ends on the next page.
    pages = [
        "Курс по базам данных\nПервая страница описывает важную инфор-\n7",
        "Курс по базам данных\nмацию о нормализации. Дальше идёт текст.\n8",
        "Курс по базам данных\nТретья страница.\n9",
    ]

    assert clean_pdf_pages(pages) == [
        "Первая страница описывает важную информацию",
        "о нормализации. Дальше идёт текст.",
        "Третья страница.",
    ]


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        (["Это инфор\N{HYPHEN}", "мация.\nДалее."], ["Это информация.", "Далее."]),
        (
            ["Это инфор-", " \n", "  мация о нормализации."],
            ["Это информация", "", "о нормализации."],
        ),
        (["Это инфор-", "Мация с заглавной."], ["Это инфор-", "Мация с заглавной."]),
        (["Номер 5-", "мация."], ["Номер 5-", "мация."]),
    ],
    ids=["whole-line", "empty-page-between", "capital-after", "digit-before"],
)
def test_only_a_word_broken_across_pages_moves_to_the_page_where_it_starts(
    pages: list[str], expected: list[str]
) -> None:
    assert clean_pdf_pages(pages) == expected


@pytest.mark.parametrize(
    "hyphen", ["-", "\N{HYPHEN}", "\xad"], ids=["hyphen-minus", "hyphen", "soft-hyphen"]
)
def test_a_hyphen_of_any_kind_at_a_line_end_joins_the_word(hyphen: str) -> None:
    assert clean_pdf_pages([f"инфор{hyphen}\nмация"]) == ["информация"]


@pytest.mark.parametrize(
    "page",
    ["Москва-\nРека", "номер 5-\n6 и далее", "слово -\nдалее", "x-\n-y"],
    ids=["capital-after", "digit-before", "space-before", "dash-after"],
)
def test_a_line_end_hyphen_that_does_not_break_a_word_is_kept(page: str) -> None:
    assert clean_pdf_pages([page]) == [page]


def test_blank_lines_and_trailing_spaces_of_pdf_pages_are_dropped() -> None:
    assert clean_pdf_pages(["\n One.  \n\n\nTwo.\n \n"]) == [" One.\nTwo."]


def test_a_page_left_without_text_keeps_its_place() -> None:
    # Later pages keep their numbers, so text can still be traced back to its page.
    assert clean_pdf_pages(["Body one.", "7", " \n", "Body four."]) == [
        "Body one.",
        "",
        "",
        "Body four.",
    ]


@pytest.mark.parametrize(
    "number",
    [
        "7",
        "  7 ",
        "Page 7",
        "page 7 of 12",
        "Стр. 7",
        "стр 7",
        "Страница 7 из 12",
        "7 / 12",
        "7/12",
        "7 из 12",
    ],
)
def test_page_numbers_on_the_first_or_last_line_are_dropped(number: str) -> None:
    page = f"{number}\nBody one.\nBody two.\nBody three.\nBody four.\n{number}"

    assert clean_pdf_pages([page]) == ["Body one.\nBody two.\nBody three.\nBody four."]


def test_page_numbers_among_the_three_lines_at_either_edge_are_dropped() -> None:
    page = "Title\nSubtitle\n7\nBody one.\nBody two.\nBody three.\n12\nNote one\nNote two"

    assert clean_pdf_pages([page]) == [
        "Title\nSubtitle\nBody one.\nBody two.\nBody three.\nNote one\nNote two"
    ]


def test_a_number_deeper_in_the_page_is_kept() -> None:
    page = "One.\nTwo.\nThree.\n42\nFive.\nSix.\nSeven."

    assert clean_pdf_pages([page]) == [page]


@pytest.mark.parametrize("line", ["Chapter 7", "7. Introduction", "2026 год", "Page seven"])
def test_a_line_with_a_number_and_words_is_not_a_page_number(line: str) -> None:
    page = f"{line}\nBody.\n{line}"

    assert clean_pdf_pages([page]) == [page]


def test_running_headers_and_footers_of_a_built_pdf_are_removed(tmp_path: Path) -> None:
    bodies = [
        ["Relations hold tuples.", "Each tuple has attributes."],
        ["Keys identify tuples.", "A foreign key refers to a key."],
        ["Joins combine relations.", "Indexes speed up lookups."],
        ["Normal forms limit redundancy.", "Anomalies follow from redundancy."],
        ["Transactions are atomic.", "Locks keep them isolated."],
    ]
    pages = [
        ["Database Systems", f"Lecture notes, part {number}", *body, f"Spring 2026, page {number}"]
        for number, body in enumerate(bodies, start=1)
    ]

    cleaned = clean_pdf_pages(_built_pdf_pages(tmp_path, pages))

    assert cleaned == ["\n".join(body) for body in bodies]


def test_body_lines_that_repeat_inside_pages_are_kept(tmp_path: Path) -> None:
    reminder = "Remember: every relation needs a key."
    pages = [
        ["Database Systems", f"Opening line {letter}.", reminder, f"Closing line {letter}."]
        for letter in "ABCD"
    ]

    cleaned = clean_pdf_pages(_built_pdf_pages(tmp_path, pages))

    assert cleaned == [
        f"Opening line {letter}.\n{reminder}\nClosing line {letter}." for letter in "ABCD"
    ]


def test_an_edge_line_shared_by_only_two_pages_is_kept() -> None:
    pages = ["Shared title\nFirst body.", "Shared title\nSecond body."]

    assert clean_pdf_pages(pages) == pages


@pytest.mark.parametrize(
    ("shared", "expected_first_lines"),
    [
        (2, ["Shared", "Shared", "Own C", "Own D", "Own E", "Own F"]),
        (3, ["Body A", "Body B", "Body C", "Own D", "Own E", "Own F"]),
    ],
    ids=["a-third-of-the-pages", "half-of-the-pages"],
)
def test_an_edge_line_must_stand_on_at_least_half_of_the_pages(
    shared: int, expected_first_lines: list[str]
) -> None:
    # Letters rather than numbers: lines that differ only in their numbers count as one.
    pages = [
        f"Shared\nBody {letter}" if index < shared else f"Own {letter}\nBody {letter}"
        for index, letter in enumerate("ABCDEF")
    ]

    cleaned = clean_pdf_pages(pages)

    assert [page.split("\n")[0] for page in cleaned] == expected_first_lines


def test_at_most_three_lines_are_removed_at_each_edge() -> None:
    header = ["Course", "Database Systems", "Spring term", "Week overview"]
    footer = ["Week overview", "Spring term", "Database Systems", "Course"]
    pages = ["\n".join([*header, f"Body of page {number}.", *footer]) for number in range(1, 5)]

    cleaned = clean_pdf_pages(pages)

    assert cleaned == [
        f"Week overview\nBody of page {number}.\nWeek overview" for number in range(1, 5)
    ]


def test_the_running_header_and_page_numbers_of_a_browser_printed_pdf_are_removed() -> None:
    pages = _pdf_pages(LECTURE_PDF)

    cleaned = clean_pdf_pages(pages)

    assert len(cleaned) == len(pages) >= 4
    assert cleaned[0].startswith("Лекция 4. Нормализация реляционных баз данных\n")
    for number, (raw, page) in enumerate(zip(pages, cleaned, strict=True), start=1):
        body = [
            line
            for line in clean_text(raw).split("\n")
            if line not in (LECTURE_HEADER, f"Стр. {number}")
        ]
        # The body keeps its words; only the line breaks between them may go.
        assert page.split() == " ".join(body).split()
    assert LECTURE_HEADER not in "\n".join(cleaned)


def test_the_paragraphs_of_a_browser_printed_pdf_become_lines_of_their_own() -> None:
    cleaned = clean_pdf_pages(_pdf_pages(LECTURE_PDF))

    title, paragraph, heading, *_ = cleaned[0].split("\n")
    assert title == "Лекция 4. Нормализация реляционных баз данных"
    assert paragraph.startswith(
        "Нормализация — это последовательное преобразование схемы базы данных, при котором "
        "каждая таблица описывает ровно одну сущность или одну связь между сущностями."
    )
    assert paragraph.endswith("и база начинает давать разные ответы на один вопрос.")
    assert heading == "Аномалии при работе с данными"
    questions = cleaned[-1].split("\n")[-5:]
    assert questions[0] == (
        "1. Какие три вида аномалий возникают в ненормализованной таблице и чем они опасны?"
    )
    assert [question[:2] for question in questions] == ["1.", "2.", "3.", "4.", "5."]


def test_lines_the_layout_wrapped_are_joined_and_the_others_kept() -> None:
    page = "\n".join(
        [
            "Нормализация реляционных баз данных",
            "Нормализация — это последовательное преобразование схемы базы",
            "данных, при котором каждая таблица описывает одну сущность.",
            "Вопросы для самопроверки",
            "1. Какие три вида аномалий возникают в ненормализованной таблице и",
            "чем они опасны?",
            "2. Чем полная функциональная зависимость отличается от частичной?",
        ]
    )

    assert clean_pdf_pages([page]) == [
        "Нормализация реляционных баз данных\n"
        "Нормализация — это последовательное преобразование схемы базы данных, при котором "
        "каждая таблица описывает одну сущность.\n"
        "Вопросы для самопроверки\n"
        "1. Какие три вида аномалий возникают в ненормализованной таблице и чем они опасны?\n"
        "2. Чем полная функциональная зависимость отличается от частичной?"
    ]


@pytest.mark.parametrize(
    "page",
    [
        "Строки таблицы читают из файла по одной, как в коротком примере:\n"
        "import csv\n"
        "rows = list(csv.reader(stream))",
        "Функция возвращает первую строку таблицы, если она есть, а иначе\n    return None",
        "Виды аномалий\nвставки\nобновления\nудаления",
        "Таблица находится во второй нормальной форме, если выполнено условие.\n"
        "т. е. каждый неключевой атрибут зависит от всего ключа",
    ],
    ids=["after-a-colon-and-short-lines", "indented-line", "short-lines-only", "after-a-stop"],
)
def test_line_breaks_that_the_writer_made_are_kept(page: str) -> None:
    assert clean_pdf_pages([page]) == [page]


@pytest.mark.parametrize("text", ["Нормализация", "2026"], ids=["letters", "digits"])
def test_text_at_the_limit_with_a_letter_or_a_digit_passes_the_check(text: str) -> None:
    check_text(text, max_chars=len(text))


def test_text_over_the_limit_is_too_long() -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        check_text("." * 11, max_chars=10)

    assert caught.value.code == "text_too_long"


@pytest.mark.parametrize(
    "text",
    ["", " \n\t ", "... — !? «» -- **", "\N{IDEOGRAPHIC SPACE}"],
    ids=["empty", "whitespace", "punctuation", "ideographic-space"],
)
def test_text_without_a_letter_or_a_digit_has_no_text(text: str) -> None:
    with pytest.raises(DocumentProcessingError) as caught:
        check_text(text, max_chars=100)

    assert caught.value.code == "no_text"


@pytest.mark.no_cover
@pytest.mark.parametrize("unit", HOSTILE_UNITS + EXPANDING_UNITS + MARK_UNITS + LINE_UNITS)
def test_long_runs_are_cleaned_in_linear_time(unit: str) -> None:
    text = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    cleaned = clean_text(text)
    with contextlib.suppress(DocumentProcessingError):
        check_text(cleaned, max_chars=HOSTILE_TEXT_LENGTH)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS


@pytest.mark.no_cover
@pytest.mark.parametrize("unit", HOSTILE_UNITS + EXPANDING_UNITS + MARK_UNITS + LINE_UNITS)
def test_long_runs_on_pdf_pages_are_cleaned_in_linear_time(unit: str) -> None:
    text = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    clean_pdf_pages([text])

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS


@pytest.mark.no_cover
def test_pages_that_each_end_inside_one_long_word_are_cleaned_in_linear_time() -> None:
    # Every page would continue the word of the page before it. Different letters keep the
    # pages from being taken for running lines.
    pages = [
        string.ascii_lowercase[number % 26] * (HOSTILE_PAGE_LENGTH - 1) + "-"
        for number in range(HOSTILE_TEXT_LENGTH // HOSTILE_PAGE_LENGTH)
    ]

    started = time.perf_counter()
    cleaned = clean_pdf_pages(pages)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
    assert len("".join(cleaned)) > HOSTILE_TEXT_LENGTH // 2
