"""Natural-language keyword query builder for hybrid RAG chat retrieval.

Extracts folded alphanumeric content words from the student's question (augmented by the most
recent user turn on short follow-ups) and joins them with "or" so PostgreSQL's
websearch_to_tsquery matches any relevant term without operator syntax errors or exclusions.
"""

# ruff: noqa: RUF001 -- Cyrillic letters are intended

import re
import unicodedata
from collections.abc import Sequence
from typing import Final

from app.documents.text import STOPWORDS_EN, STOPWORDS_RU
from app.llm.base import ChatHistoryTurn
from app.rag.vector_store import MAX_KEYWORD_QUERY_CHARS

CHAT_KEYWORD_MAX_TERMS: Final = 14
_MIN_TERM_CHARS: Final = 2
_FOLLOWUP_TRIGGER_TERMS: Final = 2
_TOKEN_MAX_CHARS: Final = 64
_PIECE_MAX_CHARS: Final = 4 * _TOKEN_MAX_CHARS
_OR_SEPARATOR: Final = " or "
_WEBSEARCH_OR_OPERATOR: Final = "or"
# Alphanumeric runs only: strips punctuation, quotes, parentheses and "-" exclusions cleanly.
_ALNUM_TOKEN_RE: Final = re.compile(r"[^\W_]++")

# Chat-only filler and question words kept separate from document analysis and embeddings.
_CHAT_QUERY_STOPWORDS: Final = (
    STOPWORDS_EN
    | STOPWORDS_RU
    | frozenset(
        {
            "about",
            "answer",
            "briefly",
            "can",
            "could",
            "define",
            "describe",
            "detail",
            "details",
            "difference",
            "different",
            "does",
            "elaborate",
            "example",
            "examples",
            "explain",
            "give",
            "help",
            "how",
            "important",
            "know",
            "list",
            "main",
            "make",
            "makes",
            "mean",
            "means",
            "more",
            "or",
            "please",
            "provide",
            "say",
            "says",
            "short",
            "show",
            "summarize",
            "summary",
            "tell",
            "understand",
            "use",
            "used",
            "using",
            "what",
            "when",
            "where",
            "which",
            "why",
            "work",
            "works",
            "более",
            "бывает",
            "бывают",
            "вопрос",
            "главное",
            "говорится",
            "давай",
            "делает",
            "делают",
            "делать",
            "еще",
            "зачем",
            "значит",
            "именно",
            "какая",
            "какие",
            "каким",
            "каких",
            "какого",
            "какое",
            "какой",
            "какую",
            "коротко",
            "кратко",
            "лучше",
            "можно",
            "надо",
            "назови",
            "например",
            "нужна",
            "нужно",
            "нужны",
            "объясни",
            "объясните",
            "означает",
            "опиши",
            "опишите",
            "основные",
            "ответь",
            "подробнее",
            "подробно",
            "пожалуйста",
            "покажи",
            "почему",
            "приведи",
            "пример",
            "примеры",
            "просто",
            "работает",
            "работают",
            "расскажи",
            "расскажите",
            "самое",
            "скажи",
            "скажите",
            "сколько",
            "стоит",
            "суть",
            "такая",
            "такие",
            "такое",
            "такой",
            "тема",
            "тему",
            "чем",
            "что",
        }
    )
)


def build_chat_keyword_query(question: str, history: Sequence[ChatHistoryTurn] = ()) -> str:
    """Build an OR-joined PostgreSQL websearch keyword query from a natural-language question.

    Augments short follow-ups (< 2 extracted terms) with terms from the most recent prior user
    turn, caps at CHAT_KEYWORD_MAX_TERMS and MAX_KEYWORD_QUERY_CHARS, and emits strictly
    alphanumeric terms with no websearch operators or punctuation.
    """
    terms = _extract_terms(question)
    if len(terms) < _FOLLOWUP_TRIGGER_TERMS:
        seen = set(terms)
        for turn in reversed(history):
            if turn.role != "user":
                continue
            prior_terms = _extract_terms(turn.content)
            if prior_terms:
                for term in prior_terms:
                    if term not in seen:
                        seen.add(term)
                        terms.append(term)
                break
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


def _extract_terms(text: str) -> list[str]:
    composed = " ".join(
        unicodedata.normalize("NFC", piece) if len(piece) <= _PIECE_MAX_CHARS else piece
        for piece in text.split()
    )
    seen: set[str] = set()
    terms: list[str] = []
    for match in _ALNUM_TOKEN_RE.finditer(composed):
        token = match.group()
        if len(token) > _TOKEN_MAX_CHARS:
            continue
        normalized = unicodedata.normalize("NFKC", token).casefold()
        # NFKC can expand compatibility characters (e.g. fractions) into punctuation; re-split
        # so every emitted term is strictly alphanumeric.
        for piece in _ALNUM_TOKEN_RE.findall(normalized):
            if (
                len(piece) < _MIN_TERM_CHARS
                or piece == _WEBSEARCH_OR_OPERATOR
                or piece.replace("ё", "е") in _CHAT_QUERY_STOPWORDS
                or piece in seen
            ):
                continue
            seen.add(piece)
            terms.append(piece)
    return terms
