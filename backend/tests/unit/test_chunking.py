import time
from typing import Final

import pytest

from app.documents.chunking import (
    HEADING_SEPARATOR,
    PAGE_SEPARATOR,
    Chunk,
    chunk_markdown,
    chunk_pdf_pages,
    chunk_plain,
    sentence_spans,
)
from app.documents.text import ELLIPSIS
from app.models.document_chunk import CHUNK_HEADING_MAX_LENGTH

SIZE: Final = 1200
OVERLAP: Final = 200
HOSTILE_TEXT_LENGTH: Final = 2_000_000
HOSTILE_UNITS: Final = (".", "!?", "…", "#", " #", "-")
# What the chunker's own patterns look for: blank lines, code fences and spaces.
LINE_UNITS: Final = ("\n", " \n", "```\n", " ")
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0
MIXED_TEXT: Final = (
    "Short one. "
    + "A much longer sentence that keeps on going " * 6
    + "until it ends.\n\n"
    + "x" * 150
    + " tail words here.\n"
    + "Слова на русском языке. Ещё одно предложение!\n\n\n"
    + "- a list item without a stop\n- another item\n"
    + "    an indented code line\n"
    + "Final sentence?"
)


def _sentences(count: int, length: int) -> list[str]:
    """Sentences of exactly length characters, each one starting a new sentence."""
    return [f"Sentence {index:02d} " + "a" * (length - 13) + "." for index in range(count)]


def _contents(chunks: list[Chunk]) -> list[str]:
    return [chunk.content for chunk in chunks]


def _headed(chunks: list[Chunk]) -> list[tuple[str | None, str]]:
    return [(chunk.heading, chunk.content) for chunk in chunks]


def _path(*titles: str) -> str:
    return HEADING_SEPARATOR.join(titles)


def test_a_short_text_is_one_chunk_without_heading_or_pages() -> None:
    assert chunk_plain("  One. Two.\n", size=SIZE, overlap=OVERLAP) == [
        Chunk(
            index=0,
            content="One. Two.",
            heading=None,
            page_start=None,
            page_end=None,
            char_count=9,
        )
    ]


@pytest.mark.parametrize("text", ["", " \n\n\t "])
def test_blank_text_has_no_chunks(text: str) -> None:
    assert chunk_plain(text, size=SIZE, overlap=OVERLAP) == []
    assert chunk_markdown(text, size=SIZE, overlap=OVERLAP) == []
    assert chunk_pdf_pages([text, text], size=SIZE, overlap=OVERLAP) == []


def test_whole_sentences_are_packed_while_they_fit_in_the_size() -> None:
    sentences = _sentences(10, 100)

    chunks = chunk_plain(" ".join(sentences), size=350, overlap=0)

    assert _contents(chunks) == [
        " ".join(sentences[0:3]),
        " ".join(sentences[3:6]),
        " ".join(sentences[6:9]),
        sentences[9],
    ]


def test_each_chunk_starts_with_the_last_sentences_of_the_one_before() -> None:
    sentences = _sentences(10, 100)

    chunks = chunk_plain(" ".join(sentences), size=350, overlap=150)

    assert _contents(chunks) == [
        " ".join(sentences[0:3]),
        " ".join(sentences[2:6]),
        " ".join(sentences[5:9]),
        " ".join(sentences[8:10]),
    ]


def test_the_overlap_takes_only_whole_sentences() -> None:
    sentences = _sentences(6, 160)

    chunks = chunk_plain(" ".join(sentences), size=350, overlap=150)

    assert _contents(chunks) == [" ".join(sentences[start : start + 2]) for start in (0, 2, 4)]


def test_the_overlap_never_repeats_a_whole_chunk() -> None:
    short = "A short opening sentence."
    long = _sentences(1, 340)[0]

    chunks = chunk_plain(f"{short} {long}", size=350, overlap=100)

    assert _contents(chunks) == [short, long]


def test_chunks_are_numbered_in_order_and_count_their_characters() -> None:
    chunks = chunk_plain(" ".join(_sentences(10, 100)), size=350, overlap=150)

    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.char_count == len(chunk.content) for chunk in chunks)


def test_a_blank_line_ends_a_sentence() -> None:
    text = "A heading-like line\n\nThe paragraph below it continues"

    assert _contents(chunk_plain(text, size=40, overlap=0)) == [
        "A heading-like line",
        "The paragraph below it continues",
    ]
    assert _contents(chunk_plain(text, size=100, overlap=0)) == [text]


def test_a_sentence_longer_than_the_size_is_cut_between_words() -> None:
    sentence = " ".join(f"word{index:03d}" for index in range(300))

    chunks = chunk_plain(sentence, size=100, overlap=0)

    assert all(chunk.char_count <= 100 for chunk in chunks)
    assert " ".join(_contents(chunks)) == sentence


def test_a_run_without_spaces_is_cut_every_size_characters() -> None:
    chunks = chunk_plain("x" * 5000, size=SIZE, overlap=OVERLAP)

    assert [chunk.char_count for chunk in chunks] == [1200, 1200, 1200, 1200, 200]
    assert "".join(_contents(chunks)) == "x" * 5000


def test_an_embedded_image_gives_chunks_no_longer_than_size_plus_overlap() -> None:
    data_uri = ("data:image/png;base64," + "iVBORw0KGgoAAAANSUhEUg" * 5000)[:100_000]
    text = f"# Schema\n\nThe schema is shown below.\n\n![schema]({data_uri})\n\nThe end."

    chunks = chunk_markdown(text, size=SIZE, overlap=OVERLAP)

    assert len(chunks) > 80
    assert all(0 < chunk.char_count <= SIZE + OVERLAP for chunk in chunks)
    assert {chunk.heading for chunk in chunks} == {"Schema"}


@pytest.mark.parametrize(("size", "overlap"), [(40, 0), (40, 39), (100, 10), (333, 50)])
def test_no_chunk_is_longer_than_size_plus_overlap_or_blank(size: int, overlap: int) -> None:
    for chunks in (
        chunk_plain(MIXED_TEXT, size=size, overlap=overlap),
        chunk_markdown(MIXED_TEXT, size=size, overlap=overlap),
        chunk_pdf_pages(MIXED_TEXT.split("\n\n"), size=size, overlap=overlap),
    ):
        assert chunks
        for chunk in chunks:
            assert 0 < chunk.char_count <= size + overlap
            assert chunk.content == chunk.content.strip()


@pytest.mark.parametrize("size", [40, 100, 333])
def test_without_overlap_every_word_is_in_exactly_one_chunk(size: int) -> None:
    chunks = chunk_plain(MIXED_TEXT, size=size, overlap=0)

    assert "".join("".join(chunk.content.split()) for chunk in chunks) == "".join(
        MIXED_TEXT.split()
    )


def test_russian_text_is_cut_at_sentence_ends() -> None:
    sentences = [
        "Нормализация устраняет избыточность данных.",
        "Первая нормальная форма требует атомарности значений.",
        "Вторая форма убирает частичные зависимости от ключа.",
        "Третья форма убирает транзитивные зависимости.",
    ]

    chunks = chunk_plain(" ".join(sentences), size=100, overlap=0)

    assert _contents(chunks) == [" ".join(sentences[0:2]), " ".join(sentences[2:4])]


def test_markdown_chunks_carry_the_path_of_their_headings() -> None:
    text = (
        "Intro before any heading.\n"
        "# Databases\n"
        "Relations hold tuples.\n"
        "## Keys\n"
        "A key identifies a tuple.\n"
        "## Normal forms\n"
        "Normal forms limit redundancy.\n"
        "# Transactions\n"
        "Transactions are atomic.\n"
    )

    assert _headed(chunk_markdown(text, size=SIZE, overlap=OVERLAP)) == [
        (None, "Intro before any heading."),
        ("Databases", "Relations hold tuples."),
        (_path("Databases", "Keys"), "A key identifies a tuple."),
        (_path("Databases", "Normal forms"), "Normal forms limit redundancy."),
        ("Transactions", "Transactions are atomic."),
    ]


def test_a_heading_path_skips_missing_levels_and_closes_deeper_ones() -> None:
    text = "# A\n### C\nUnder C.\n## B\nUnder B.\n#\nUnder an empty heading."

    assert _headed(chunk_markdown(text, size=SIZE, overlap=OVERLAP)) == [
        (_path("A", "C"), "Under C."),
        (_path("A", "B"), "Under B."),
        (None, "Under an empty heading."),
    ]


@pytest.mark.parametrize(
    ("line", "heading"),
    [
        ("## Normal forms ##", "Normal forms"),
        ("#   Spaced\tout   title  ", "Spaced out title"),
        ("   # Three spaces in", "Three spaces in"),
        ("# C#", "C#"),
        ("# Нормализация", "Нормализация"),
    ],
    ids=["closing-hashes", "whitespace", "indented", "hash-in-a-word", "cyrillic"],
)
def test_heading_lines_give_their_text(line: str, heading: str) -> None:
    assert _headed(chunk_markdown(f"{line}\nBody.", size=SIZE, overlap=OVERLAP)) == [
        (heading, "Body.")
    ]


@pytest.mark.parametrize(
    "line",
    ["#hashtag", "####### Seven levels", "    # Indented code", "\t# Tabbed"],
    ids=["no-space", "seven-levels", "four-spaces", "tab"],
)
def test_lines_that_are_not_headings_stay_in_the_text(line: str) -> None:
    text = f"{line}\nBody."

    assert _headed(chunk_markdown(text, size=SIZE, overlap=OVERLAP)) == [(None, text.strip())]


def test_hash_lines_inside_code_blocks_are_not_headings() -> None:
    code = "```python\n# a comment, not a heading\nprint(1)\n```"
    tilde_code = "~~~\n```\n# still code\n~~~"
    text = f"# Code\n{code}\nAfter the code.\n## Next\n{tilde_code}"

    assert _headed(chunk_markdown(text, size=SIZE, overlap=OVERLAP)) == [
        ("Code", f"{code}\nAfter the code."),
        (_path("Code", "Next"), tilde_code),
    ]


def test_chunks_and_their_overlap_stay_within_their_section() -> None:
    first = _sentences(3, 100)
    second = [sentence.replace("Sentence", "Clause") for sentence in _sentences(3, 100)]
    text = "# One\n" + " ".join(first) + "\n# Two\n" + " ".join(second)

    chunks = chunk_markdown(text, size=250, overlap=150)

    assert _headed(chunks) == [
        ("One", " ".join(first[0:2])),
        ("One", " ".join(first[1:3])),
        ("Two", " ".join(second[0:2])),
        ("Two", " ".join(second[1:3])),
    ]


def test_long_heading_paths_lose_their_leading_levels_first() -> None:
    titles = [f"Level {level} heading" + " word" * 21 for level in range(1, 6)]
    headings = "\n".join(f"{'#' * level} {title}" for level, title in enumerate(titles, start=1))

    chunks = chunk_markdown(f"{headings}\nBody.", size=SIZE, overlap=OVERLAP)

    assert all(len(title) == 120 for title in titles)
    assert _headed(chunks) == [(_path(*titles[1:]), "Body.")]
    assert len(_path(*titles[1:])) <= CHUNK_HEADING_MAX_LENGTH


def test_a_single_heading_over_the_limit_is_cut_at_a_word_boundary() -> None:
    title = " ".join(["word"] * 200)

    [chunk] = chunk_markdown(f"# {title}\nBody.", size=SIZE, overlap=OVERLAP)

    assert chunk.heading is not None
    assert len(chunk.heading) <= CHUNK_HEADING_MAX_LENGTH
    assert chunk.heading.endswith(ELLIPSIS)
    assert set(chunk.heading.removesuffix(ELLIPSIS).split(" ")) == {"word"}


def test_a_document_of_headings_only_is_chunked_as_plain_text() -> None:
    text = "# Title\n## Subtitle\n"

    assert chunk_markdown(text, size=SIZE, overlap=OVERLAP) == chunk_plain(
        text, size=SIZE, overlap=OVERLAP
    )
    assert _headed(chunk_markdown(text, size=SIZE, overlap=OVERLAP)) == [
        (None, "# Title\n## Subtitle")
    ]


def test_pdf_chunks_know_the_pages_they_come_from() -> None:
    pages = ["Alpha one. Alpha two.", "Beta one. Beta two.", "", "Gamma one. Gamma two."]

    chunks = chunk_pdf_pages(pages, size=45, overlap=0)

    assert [(chunk.content, chunk.page_start, chunk.page_end) for chunk in chunks] == [
        (f"Alpha one. Alpha two.{PAGE_SEPARATOR}Beta one. Beta two.", 1, 2),
        ("Gamma one. Gamma two.", 4, 4),
    ]
    assert {chunk.heading for chunk in chunks} == {None}


def test_a_sentence_that_runs_on_to_the_next_page_stays_whole() -> None:
    sentence = "The first sentence runs on\nto the next page."
    pages = ["The first sentence runs on", "to the next page. Then another one."]

    chunks = chunk_pdf_pages(pages, size=len(sentence), overlap=0)

    assert [(chunk.content, chunk.page_start, chunk.page_end) for chunk in chunks] == [
        (sentence, 1, 2),
        ("Then another one.", 2, 2),
    ]


def test_chunking_is_deterministic() -> None:
    assert chunk_markdown(MIXED_TEXT, size=100, overlap=30) == chunk_markdown(
        MIXED_TEXT, size=100, overlap=30
    )


def test_sentence_spans_end_at_sentence_ends_and_blank_lines() -> None:
    text = "One. Two!\n\nThree without a stop\nstill three"

    spans = sentence_spans(text, 0, len(text), max_chars=100)

    assert [text[start:end] for start, end in spans] == [
        "One.",
        "Two!",
        "Three without a stop\nstill three",
    ]
    assert sentence_spans(text, 5, 9, max_chars=100) == [(5, 9)]


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (10, -1)])
def test_a_size_below_one_or_a_negative_overlap_is_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="size"):
        chunk_plain("Text.", size=size, overlap=overlap)


@pytest.mark.parametrize("max_chars", [0, -5])
def test_sentence_spans_reject_a_limit_below_one(max_chars: int) -> None:
    with pytest.raises(ValueError, match="max_chars"):
        sentence_spans("Text.", 0, 5, max_chars=max_chars)


@pytest.mark.parametrize("unit", HOSTILE_UNITS + LINE_UNITS)
def test_long_runs_are_chunked_in_linear_time(unit: str) -> None:
    text = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    chunk_markdown(text, size=SIZE, overlap=OVERLAP)
    chunk_plain(text, size=SIZE, overlap=OVERLAP)
    chunk_pdf_pages([text], size=SIZE, overlap=OVERLAP)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
