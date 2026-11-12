import random
import time
from itertools import pairwise
from typing import Final

import pytest

from app.rag.snippets import MAX_SNIPPET_CHARS, parse_headline
from app.rag.vector_store import FRAGMENT_DELIMITER as DELIMITER
from app.rag.vector_store import HIGHLIGHT_START as START
from app.rag.vector_store import HIGHLIGHT_STOP as STOP
from app.schemas.search import SnippetPart

HOSTILE_TEXT_LENGTH: Final = 2_000_000
# Marks without their partners, alone or around spaces and letters.
MARK_UNITS: Final = (
    START,
    STOP,
    DELIMITER,
    START + STOP,
    STOP + START,
    f"{START} {STOP}",
    f"{START}a{STOP}",
    f"{DELIMITER} ",
    f"{START}{DELIMITER}{STOP}",
)
# Runs of whitespace, and words that fill a snippet at once.
SPACE_UNITS: Final = (" ", "\n", " \r\n\t", "a ", "x")
# Timed with coverage's tracer paused (no_cover): tracing multiplies the time of every step.
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0
_SEED: Final = 20261112
_MIXED_ALPHABET: Final = (START, STOP, DELIMITER, " ", "\n", "a", "b", "я")
_LONG_WORD: Final = "x" * (MAX_SNIPPET_CHARS + 1)
# What is left of it beside the space and the ellipsis that mark the cut.
_LONG_WORD_KEPT: Final = "x" * (MAX_SNIPPET_CHARS - 2)


def _plain(text: str) -> SnippetPart:
    return SnippetPart(text=text, highlighted=False)


def _marked(text: str) -> SnippetPart:
    return SnippetPart(text=text, highlighted=True)


def _text(parts: list[SnippetPart]) -> str:
    return "".join(part.text for part in parts)


def test_words_between_a_start_and_a_stop_are_highlighted() -> None:
    assert parse_headline(f"The {START}light{STOP} reaction") == [
        _plain("The "),
        _marked("light"),
        _plain(" reaction"),
    ]


def test_passages_are_joined_by_an_ellipsis_between_spaces() -> None:
    assert parse_headline(f"in the thylakoid membranes{DELIMITER}the Calvin cycle") == [
        _plain("in the thylakoid membranes … the Calvin cycle")
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            f"light{DELIMITER}{START}reaction{STOP} ends",
            [_plain("light … "), _marked("reaction"), _plain(" ends")],
        ),
        (f"{START}light{STOP}{DELIMITER}reaction", [_marked("light"), _plain(" … reaction")]),
    ],
    ids=["before-a-highlight", "after-a-highlight"],
)
def test_a_passage_break_beside_a_highlighted_word_stays_plain(
    raw: str, expected: list[SnippetPart]
) -> None:
    # What ts_headline writes when a passage begins or ends with a word that the query matched.
    assert parse_headline(raw) == expected


def test_every_run_of_whitespace_becomes_one_space() -> None:
    assert parse_headline("Chapter 3.\n\nThe  light \t reaction\r\nends") == [
        _plain("Chapter 3. The light reaction ends")
    ]


def test_the_snippet_starts_and_ends_without_a_space() -> None:
    assert parse_headline(f" \n {START}light{STOP} reaction \n") == [
        _marked("light"),
        _plain(" reaction"),
    ]


def test_only_words_are_highlighted_never_the_spaces_around_or_between_them() -> None:
    assert parse_headline(f"the{START} light  reaction {STOP}cycle") == [
        _plain("the "),
        _marked("light"),
        _plain(" "),
        _marked("reaction"),
        _plain(" cycle"),
    ]


def test_neighbouring_parts_of_the_same_kind_become_one_part() -> None:
    assert parse_headline(f"{START}light{STOP}{START}s{STOP} and{STOP} water") == [
        _marked("lights"),
        _plain(" and water"),
    ]


def test_empty_parts_are_dropped() -> None:
    assert parse_headline(f"{START}{STOP}light{START} {STOP}water") == [_plain("light water")]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"{START}light reaction", [_plain("light reaction")]),
        (f"light{STOP} reaction", [_plain("light reaction")]),
        (f"{STOP}light{START} reaction", [_plain("light reaction")]),
        (f"{START}light{DELIMITER}reaction{STOP}", [_plain("light … reaction")]),
        (f"{START}light {START}reaction{STOP}", [_plain("light "), _marked("reaction")]),
        (f"{START}{START}light{STOP}{STOP}", [_marked("light")]),
    ],
    ids=[
        "start-only",
        "stop-only",
        "stop-before-start",
        "across-passages",
        "two-starts",
        "doubled",
    ],
)
def test_a_mark_without_its_partner_is_dropped(raw: str, expected: list[SnippetPart]) -> None:
    assert parse_headline(raw) == expected


def test_any_mix_of_marks_spaces_and_letters_reads_as_its_passages_joined_by_an_ellipsis() -> None:
    rng = random.Random(_SEED)  # noqa: S311 -- reproducible test headlines, not secrets
    for _ in range(2_000):
        raw = "".join(rng.choices(_MIXED_ALPHABET, k=rng.randrange(30)))

        parts = parse_headline(raw)

        # Starts and stops leave no trace in the text; each delimiter ends a passage, and
        # passages without words are left out.
        unmarked = raw.replace(START, "").replace(STOP, "")
        passages = (" ".join(passage.split()) for passage in unmarked.split(DELIMITER))
        assert _text(parts) == " … ".join(passage for passage in passages if passage)
        assert all(part.text for part in parts)
        assert all(part.text == part.text.strip() for part in parts if part.highlighted)
        assert all(left.highlighted != right.highlighted for left, right in pairwise(parts))


def test_a_delimiter_at_an_edge_or_after_another_leaves_one_ellipsis_between_passages() -> None:
    raw = f"{DELIMITER}light{DELIMITER}{DELIMITER} {DELIMITER}reaction{DELIMITER}"

    assert parse_headline(raw) == [_plain("light … reaction")]


def test_a_headline_without_marks_is_one_plain_part() -> None:
    # What PostgreSQL returns for a chunk that the query's words do not match: its first words.
    headline = "Mitochondria are the site of cellular respiration.\nThey"

    assert parse_headline(headline) == [
        _plain("Mitochondria are the site of cellular respiration. They")
    ]


@pytest.mark.parametrize(
    "raw",
    ["", " \n\t", START + STOP, DELIMITER, f"{START} {STOP}{DELIMITER}\n"],
    ids=["empty", "whitespace", "empty-highlight", "delimiter", "marks-and-whitespace"],
)
def test_a_headline_without_words_gives_no_parts(raw: str) -> None:
    assert parse_headline(raw) == []


def test_a_snippet_of_exactly_the_limit_is_kept_whole() -> None:
    raw = "x" * MAX_SNIPPET_CHARS

    assert parse_headline(raw) == [_plain(raw)]


def test_a_longer_snippet_is_cut_before_the_word_that_does_not_fit() -> None:
    # Every word takes five characters with its space: 119 of them fill 594 characters,
    # and the 120th would leave no room for the ellipsis.
    parts = parse_headline("abcd " * 200)

    assert parts == [_plain(" ".join(["abcd"] * 119) + " …")]
    assert len(_text(parts)) <= MAX_SNIPPET_CHARS


def test_a_cut_after_a_highlighted_word_ends_with_a_plain_ellipsis() -> None:
    raw = "abcd " * 118 + f"{START}light{STOP}" + " more" * 50

    parts = parse_headline(raw)

    assert parts == [_plain("abcd " * 118), _marked("light"), _plain(" …")]
    assert len(_text(parts)) <= MAX_SNIPPET_CHARS


def test_a_cut_where_a_passage_begins_leaves_a_single_ellipsis() -> None:
    parts = parse_headline("abcd " * 119 + f"{DELIMITER}more words")

    assert parts == [_plain(" ".join(["abcd"] * 119) + " …")]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"{_LONG_WORD} reaction", [_plain(f"{_LONG_WORD_KEPT} …")]),
        (f"{START}{_LONG_WORD}{STOP} reaction", [_marked(_LONG_WORD_KEPT), _plain(" …")]),
    ],
    ids=["plain", "highlighted"],
)
def test_a_first_word_longer_than_the_limit_is_cut_through(
    raw: str, expected: list[SnippetPart]
) -> None:
    parts = parse_headline(raw)

    assert parts == expected
    assert len(_text(parts)) == MAX_SNIPPET_CHARS


def test_a_russian_headline_is_split_into_its_parts() -> None:
    # What PostgreSQL returns for a Russian lecture passage and the query "световая фаза".
    headline = (
        f"Фотосинтез.\n{START}Световая{STOP} {START}фаза{STOP} идёт на мембранах тилакоидов;"
        f" темновая {START}фаза{STOP} (цикл Кальвина) идёт в строме. Дополнительный текст без"
        " ключевых слов. Дополнительный текст без ключевых слов"
        f"{DELIMITER}Дополнительный текст без ключевых слов. Дополнительный текст без ключевых"
        f" слов. Снова {START}световая{STOP} {START}фаза{STOP}"
    )

    assert parse_headline(headline) == [
        _plain("Фотосинтез. "),
        _marked("Световая"),
        _plain(" "),
        _marked("фаза"),
        _plain(" идёт на мембранах тилакоидов; темновая "),
        _marked("фаза"),
        _plain(
            " (цикл Кальвина) идёт в строме. Дополнительный текст без ключевых слов."
            " Дополнительный текст без ключевых слов … Дополнительный текст без ключевых"
            " слов. Дополнительный текст без ключевых слов. Снова "
        ),
        _marked("световая"),
        _plain(" "),
        _marked("фаза"),
    ]


def test_a_headline_as_postgresql_writes_it_becomes_parts() -> None:
    # What ts_headline returns, with the store's options, for a lecture paragraph and the
    # query "light reaction": two passages, every matching word marked.
    headline = (
        f"Chapter 3. Photosynthesis\nThe {START}light{STOP} {START}reaction{STOP} takes place"
        " in the thylakoid membranes.\nWater is split, oxygen is released and ATP is formed."
        f" Filler words{DELIMITER}fragments of text. Later, the Calvin cycle uses ATP from the"
        f" {START}light{STOP} {START}reaction{STOP} to fix carbon dioxide"
    )

    assert parse_headline(headline) == [
        _plain("Chapter 3. Photosynthesis The "),
        _marked("light"),
        _plain(" "),
        _marked("reaction"),
        _plain(
            " takes place in the thylakoid membranes. Water is split, oxygen is released and"
            " ATP is formed. Filler words … fragments of text. Later, the Calvin cycle uses"
            " ATP from the "
        ),
        _marked("light"),
        _plain(" "),
        _marked("reaction"),
        _plain(" to fix carbon dioxide"),
    ]


@pytest.mark.no_cover
@pytest.mark.parametrize("unit", MARK_UNITS + SPACE_UNITS)
def test_long_runs_are_parsed_in_linear_time(unit: str) -> None:
    raw = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    parts = parse_headline(raw)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
    assert len(_text(parts)) <= MAX_SNIPPET_CHARS
