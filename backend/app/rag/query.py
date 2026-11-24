"""Natural-language keyword and embedding query builders for hybrid RAG chat retrieval.

Extracts folded alphanumeric content words from the student's question (augmented by the most
recent substantive user turn on short follow-ups) and joins them with "or" so PostgreSQL's
websearch_to_tsquery matches any relevant term without operator syntax errors or exclusions.
"""

# ruff: noqa: RUF001 -- Cyrillic letters are intended

import re
import unicodedata
from collections.abc import Sequence
from typing import Final

from app.documents.text import CHAT_STOPWORDS, shorten, word_matches
from app.llm.base import ChatHistoryTurn
from app.rag.vector_store import MAX_KEYWORD_QUERY_CHARS

CHAT_KEYWORD_MAX_TERMS: Final = 14
MAX_EMBEDDING_QUERY_CHARS: Final = 1000
_MIN_TERM_CHARS: Final = 2
_FOLLOWUP_TRIGGER_TERMS: Final = 2
_TOKEN_MAX_CHARS: Final = 64
_PIECE_MAX_CHARS: Final = 4 * _TOKEN_MAX_CHARS
_OR_SEPARATOR: Final = " or "
_WEBSEARCH_OR_OPERATOR: Final = "or"
# Alphanumeric runs only: strips punctuation, quotes, parentheses and "-" exclusions cleanly.
_ALNUM_TOKEN_RE: Final = re.compile(r"[^\W_]++")


def build_chat_keyword_query(question: str, history: Sequence[ChatHistoryTurn] = ()) -> str:
    """Build an OR-joined PostgreSQL websearch keyword query from a natural-language question.

    Augments short follow-ups (< 2 extracted terms) with terms from the most recent prior user
    turn, caps at CHAT_KEYWORD_MAX_TERMS and MAX_KEYWORD_QUERY_CHARS, and emits strictly
    alphanumeric terms with no websearch operators or punctuation.
    """
    terms = _extract_terms(question)
    if len(terms) < _FOLLOWUP_TRIGGER_TERMS:
        prior = _last_substantive_user_turn(history)
        if prior is not None:
            _, prior_terms = prior
            seen = set(terms)
            for term in prior_terms:
                if term not in seen:
                    seen.add(term)
                    terms.append(term)
    kept: list[str] = []
    length = 0
    for term in terms:
        if len(kept) == CHAT_KEYWORD_MAX_TERMS:
            break
        added = len(term) + (len(_OR_SEPARATOR) if kept else 0)
        if length + added > MAX_KEYWORD_QUERY_CHARS:
            break
        kept.append(term)
        length += added
    return _OR_SEPARATOR.join(kept)


def build_chat_embedding_query(
    cleaned_question: str, history: Sequence[ChatHistoryTurn] = ()
) -> str:
    """Build the query text to embed, appending the prior user turn on short follow-ups."""
    question = " ".join(cleaned_question.split())
    if not question:
        return ""
    if len(_extract_terms(question)) < _FOLLOWUP_TRIGGER_TERMS:
        prior = _last_substantive_user_turn(history)
        if prior is not None:
            prior_text, _ = prior
            prior_collapsed = " ".join(prior_text.split())
            return shorten(f"{question} {prior_collapsed}", MAX_EMBEDDING_QUERY_CHARS)
    return shorten(question, MAX_EMBEDDING_QUERY_CHARS)


def _last_substantive_user_turn(
    history: Sequence[ChatHistoryTurn],
) -> tuple[str, list[str]] | None:
    for turn in reversed(history):
        if turn.role != "user":
            continue
        terms = _extract_terms(turn.content)
        if terms:
            return turn.content, terms
    return None


def _extract_terms(text: str) -> list[str]:
    composed = " ".join(
        unicodedata.normalize("NFC", piece) if len(piece) <= _PIECE_MAX_CHARS else piece
        for piece in text.split()
    )
    seen: set[str] = set()
    terms: list[str] = []
    for match in word_matches(composed):
        token = match.group()
        if len(token) > _TOKEN_MAX_CHARS:
            continue
        normalized = unicodedata.normalize("NFKC", token).casefold()
        # Check whole words (including contractions such as "doesn't" or "you're") before
        # splitting to alphanumeric runs for websearch_to_tsquery.
        if normalized.replace("ё", "е").replace("\u2019", "'") in CHAT_STOPWORDS:
            continue
        for piece in _ALNUM_TOKEN_RE.findall(normalized):
            if (
                len(piece) < _MIN_TERM_CHARS
                or piece == _WEBSEARCH_OR_OPERATOR
                or piece.replace("ё", "е") in CHAT_STOPWORDS
                or piece in seen
            ):
                continue
            seen.add(piece)
            terms.append(piece)
    return terms
