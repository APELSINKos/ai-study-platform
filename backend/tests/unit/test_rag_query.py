# ruff: noqa: RUF001 -- Russian sample text is intended

import time
from typing import Final

import pytest

from app.documents.text import ELLIPSIS
from app.llm.base import ChatHistoryTurn
from app.rag.query import (
    CHAT_KEYWORD_MAX_TERMS,
    MAX_EMBEDDING_QUERY_CHARS,
    build_chat_embedding_query,
    build_chat_keyword_query,
)
from app.rag.vector_store import MAX_KEYWORD_QUERY_CHARS

HOSTILE_TEXT_LENGTH: Final = 2_000_000
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0


def test_extracts_unique_folded_english_content_words_joined_with_or() -> None:
    query = build_chat_keyword_query("How does review slow down forgetting a lecture? Review!")

    assert query == "review or slow or forgetting or lecture"


def test_extracts_russian_content_words_preserving_yo_while_filtering_stopwords() -> None:
    assert (
        build_chat_keyword_query("Что такое четвёртая нормальная форма и ещё примеры?")
        == "четвёртая or нормальная or форма"
    )
    assert (
        build_chat_keyword_query("Что такое нормализация баз данных?")
        == "нормализация or баз or данных"
    )


def test_strips_websearch_operators_punctuation_and_single_char_tokens() -> None:
    query = build_chat_keyword_query(
        'What about -excluded "exact phrase" OR (a + b) photo-synthesis & SM-2?'
    )

    assert query == "excluded or exact or phrase or photo or synthesis or sm"
    assert "-" not in query
    assert '"' not in query
    assert "(" not in query
    assert ")" not in query


def test_augments_short_followups_with_the_most_recent_user_turn() -> None:
    history = (
        ChatHistoryTurn(role="user", content="What is database normalization?"),
        ChatHistoryTurn(role="assistant", content="Normalization removes redundancy [1]."),
        ChatHistoryTurn(role="user", content="How does denormalization work?"),
        ChatHistoryTurn(role="assistant", content="Denormalization adds redundancy [1]."),
    )

    assert build_chat_keyword_query("Tell me more", history) == "denormalization"
    assert build_chat_keyword_query("What about caching?", history) == "caching or denormalization"
    assert build_chat_keyword_query("Расскажи подробнее", history) == "denormalization"


def test_does_not_augment_when_question_already_has_at_least_two_keywords() -> None:
    history = (ChatHistoryTurn(role="user", content="What is database normalization?"),)

    assert build_chat_keyword_query("How does spaced repetition work?", history) == (
        "spaced or repetition"
    )


def test_skips_prior_assistant_turns_and_empty_user_followups() -> None:
    history = (
        ChatHistoryTurn(role="user", content="Explain spaced repetition"),
        ChatHistoryTurn(role="assistant", content="Assistant mentions unrelated xylophone."),
        ChatHistoryTurn(role="user", content="Tell me more"),
    )

    assert build_chat_keyword_query("Please elaborate", history) == "spaced or repetition"


def test_caps_term_count_and_total_character_length() -> None:
    many_words = " ".join(f"concept{index:02}" for index in range(30))
    long_words = " ".join(f"terminology{index:02}" + "x" * 30 for index in range(12))

    capped_count = build_chat_keyword_query(many_words)
    capped_chars = build_chat_keyword_query(long_words)

    assert len(capped_count.split(" or ")) == CHAT_KEYWORD_MAX_TERMS
    assert len(capped_count) <= MAX_KEYWORD_QUERY_CHARS
    assert len(capped_chars) <= MAX_KEYWORD_QUERY_CHARS
    assert capped_chars


def test_returns_empty_string_when_no_content_words_remain() -> None:
    assert build_chat_keyword_query("??? --- or the and a 1") == ""
    assert build_chat_keyword_query("Tell me more") == ""


def test_ignores_overlong_non_word_blobs_and_handles_nfkc_compatibility_forms() -> None:
    blob = "a" * 100
    query = build_chat_keyword_query(f"ＳＱＬ ﬁle ½ {blob} memory")

    assert query == "sql or file or memory"


def test_filters_english_contractions_without_leaking_fragments() -> None:
    query = build_chat_keyword_query(
        "Why doesn't, don't, isn't, you're, we've, it'll, doesn\u2019t stop Codd's normalization?"
    )

    assert query == "stop or codd or normalization"


def test_enforces_exact_64_and_65_char_token_boundary() -> None:
    exact_64 = "a" * 64
    over_65 = "b" * 65

    assert build_chat_keyword_query(f"{exact_64} {over_65}") == exact_64


def test_build_chat_embedding_query_augments_short_followups_and_caps_length() -> None:
    history = (
        ChatHistoryTurn(role="user", content="Explain relational database normalization."),
        ChatHistoryTurn(role="assistant", content="Normalization reduces redundancy [1]."),
        ChatHistoryTurn(role="user", content="Tell me more"),
        ChatHistoryTurn(role="assistant", content="More details [1]."),
    )

    assert (
        build_chat_embedding_query("Why?", history)
        == "Why? Explain relational database normalization."
    )
    assert (
        build_chat_embedding_query("Расскажи подробнее", history)
        == "Расскажи подробнее Explain relational database normalization."
    )
    assert (
        build_chat_embedding_query("What about caching?", history)
        == "What about caching? Explain relational database normalization."
    )
    # Substantive questions (>= 2 terms) are not augmented with prior turns.
    assert (
        build_chat_embedding_query("How does spaced repetition work?", history)
        == "How does spaced repetition work?"
    )

    long_prior = " ".join(f"concept{index}" for index in range(250))
    capped = build_chat_embedding_query("Why?", (ChatHistoryTurn(role="user", content=long_prior),))
    assert len(capped) <= MAX_EMBEDDING_QUERY_CHARS
    assert capped.startswith("Why? concept0")
    assert capped.endswith(ELLIPSIS)


@pytest.mark.no_cover
@pytest.mark.parametrize("unit", ["word ", "…", "-", "a"])
def test_build_chat_keyword_query_stays_linear_on_hostile_input(unit: str) -> None:
    hostile = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    result = build_chat_keyword_query(hostile)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
    assert len(result) <= MAX_KEYWORD_QUERY_CHARS
