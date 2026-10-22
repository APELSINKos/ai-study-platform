"""Offline providers: hashed word embeddings and a heuristic document analysis.

Both are deterministic and need neither a network nor a key, so documents can be processed
with no AI provider configured. Everything here runs on untrusted document text and stays
linear on hostile input.
"""

# ruff: noqa: RUF001, RUF002 -- Cyrillic letters and typographic quotes are meant

import hashlib
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from app.documents.text import (
    EXCERPT_SEPARATOR,
    STOPWORDS_EN,
    STOPWORDS_RU,
    has_cyrillic,
    shorten,
    split_sentences,
    words,
)
from app.llm.base import EMBEDDING_DIMENSIONS, AnalysisRequest, AnalysisResult, Difficulty
from app.llm.schemas import TOPIC_MAX_LENGTH, DocumentAnalysis
from app.models.document import TITLE_MAX_LENGTH

MOCK_EMBEDDING_MODEL: Final = "mock-hashing-v1"
MOCK_ANALYSIS_MODEL: Final = "mock-heuristic-v1"

# Changing how vectors are built changes every stored vector: give it a new model name.
PREFIX_LENGTH: Final = 5
BIGRAM_WEIGHT: Final = 0.5
# Longer runs of letters are data such as base64 rather than words.
TOKEN_MAX_CHARS: Final = 64
# Text between spaces up to this length is composed before it is split into words: room for
# the longest word kept, even with combining marks on its letters. Longer runs stay as they
# are, because CPython normalises a long run that expands in quadratic time.
_PIECE_MAX_CHARS: Final = 4 * TOKEN_MAX_CHARS
_HASH_PERSON: Final = b"recall-v1"
_HASH_BYTES: Final = 8
_SIGN_BIT: Final = _HASH_BYTES * 8 - 1
_EMPTY_TEXT_FEATURE: Final = "\x00empty"
_STOPWORDS: Final = STOPWORDS_EN | STOPWORDS_RU

TITLE_LINE_MIN_CHARS: Final = 3
TITLE_LINE_MAX_CHARS: Final = 120
TITLE_SENTENCE_MAX_CHARS: Final = 80
SUMMARY_SENTENCES: Final = 3
SUMMARY_MIN_WORDS: Final = 6
SUMMARY_MAX_WORDS: Final = 60
SUMMARY_MAX_CHARS: Final = 600
TOPIC_COUNT: Final = 5
TOPIC_MIN_CHARS: Final = 4
TOPIC_STEM_CHARS: Final = 6
# Flesch reading ease: base - a * words per sentence - b * syllables per word. English uses
# the original weights, Russian a common adaptation; the thresholds are tuned on this
# project's samples, not taken from a published scale.
FLESCH_BASE: Final = 206.835
FLESCH_WEIGHTS_EN: Final = (1.015, 84.6)
FLESCH_WEIGHTS_RU: Final = (1.3, 60.1)
EASY_MIN_READING_EASE: Final = 60.0
MEDIUM_MIN_READING_EASE: Final = 30.0
READABILITY_MIN_WORDS: Final = 3
# For samples with no sentence to measure, such as tables, lists or formulas.
DEFAULT_DIFFICULTY: Final[Difficulty] = "medium"

_MARKDOWN_MAX_INDENT: Final = 3
_MARKDOWN_MAX_HEADING_LEVEL: Final = 6
_CODE_FENCES: Final = ("```", "~~~")
# Notes from Obsidian, Jekyll or Hugo can start with metadata in YAML between these lines.
_FRONT_MATTER_START: Final = "---"
_FRONT_MATTER_ENDS: Final = ("---", "...")
_FRONT_MATTER_TITLE_KEY: Final = "title"
_QUOTES: Final = "\"'"
# A line of an HTML block, such as a centred logo, or a row of a table: markup, not prose.
_MARKUP_LINE_RE: Final = re.compile(r"[ \t]*+(?:<[A-Za-z/!]|\|)")
_EXCERPT_SEPARATOR_LINE: Final = EXCERPT_SEPARATOR.strip()
_TITLE_LINE_ENDINGS: Final = (".", "!", "?", "…", ":", ";", ",")
_SENTENCE_END_CHARS: Final = ".!?…"
_LETTER_RE: Final = re.compile(r"[^\W\d_]")
_ALNUM_RE: Final = re.compile(r"[^\W_]")
_DIGIT_RE: Final = re.compile(r"\d")
_VOWEL_GROUP_RE: Final = re.compile(r"[aeiouyаеёиоуыэюя]++", re.IGNORECASE)
# Markdown list markers and the bullets that text extracted from PDF slides starts lines with.
# Dashes are left out: in wrapped text a line may start with a dash mid-sentence.
_LIST_ITEM_RE: Final = re.compile(r"(?:[-*+•◦▪‣]|\d{1,9}[.)])[ \t]++")
# Images go, and badges with them, which are images inside links; other links keep their
# text. Runs of emphasis and code marks at the edges of words go, while those inside words
# (snake_case, 2*3, x**2) stay. A run of marks can match only from its first mark: "_" is a
# word character, so without that anchor a run between two letters would be scanned again
# from each of its marks.
_INLINE_MARKUP_RE: Final = re.compile(
    r"\[!\[[^\[\]]*+\]\([^()\s]*+\)\]\([^()\s]*+\)|!\[[^\[\]]*+\]\([^()\s]*+\)"
    r"|\[([^\[\]]*+)\]\([^()\s]*+\)|`++|(?<![\w*~])[*_~]++|(?<![*_~])[*_~]++(?!\w)"
)
# A web address names no topic, although its parts look like words.
_WEB_ADDRESS_RE: Final = re.compile(r"\b(?:https?://|www\.)\S++", re.IGNORECASE)
_FILENAME_SEPARATORS: Final = str.maketrans("_.-", "   ")


class HashingEmbeddingProvider:
    """Vectors from hashed words, word beginnings and word pairs, the same in every process.

    Texts that share words get similar vectors, which is enough to try search offline.
    Python's hash() is salted per process, so the features are hashed with blake2b.
    """

    @property
    def model_name(self) -> str:
        return MOCK_EMBEDDING_MODEL

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [_embed(text) for text in texts]


class MockLLMProvider:
    """A title, summary, topics and difficulty taken from the text itself."""

    @property
    def model_name(self) -> str:
        return MOCK_ANALYSIS_MODEL

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult:
        sample = _read_sample(request.sample)
        sentences = [
            sentence for paragraph in sample.paragraphs for sentence in split_sentences(paragraph)
        ]
        title = _title(sample, sentences, request.filename)
        topic_text = _WEB_ADDRESS_RE.sub(
            " ", "\n".join([request.outline, *sample.headings, *sample.paragraphs])
        )
        analysis = DocumentAnalysis(
            title=title,
            summary=_summary(sentences),
            topics=_topics(topic_text) or [shorten(title, TOPIC_MAX_LENGTH)],
            difficulty=_difficulty(sentences),
        )
        return AnalysisResult(
            analysis=analysis, model=MOCK_ANALYSIS_MODEL, prompt_tokens=0, completion_tokens=0
        )


def _fold(word: str) -> str:
    """The form words are compared in: NFKC, case-folded, ё as е and ’ as an apostrophe."""
    return unicodedata.normalize("NFKC", word).casefold().replace("ё", "е").replace("’", "'")


def _folded_words(text: str) -> Iterator[tuple[str, str]]:
    """Each word of a text with its folded form, stop words and overlong runs left out.

    A combining mark is not a word character, so the text is composed to NFC first, piece
    by piece, or "ё" written as "е" and a diaeresis would split its word in two. Words are
    folded one at a time: CPython grows the NFKC result a few characters at a time, which
    is quadratic on a long run that expands, such as "…" turning into "...".
    """
    composed = " ".join(
        unicodedata.normalize("NFC", piece) if len(piece) <= _PIECE_MAX_CHARS else piece
        for piece in text.split()
    )
    for word in words(composed):
        if len(word) <= TOKEN_MAX_CHARS and (folded := _fold(word)) not in _STOPWORDS:
            yield word, folded


def _sublinear(count: int) -> float:
    return 1.0 + math.log(count)


def _features(text: str) -> dict[str, float]:
    """Weighted features: words, the beginnings of long words and pairs of adjacent words."""
    tokens = [folded for _, folded in _folded_words(text) if not folded.isdigit()]
    prefixes = Counter(token[:PREFIX_LENGTH] for token in tokens if len(token) > PREFIX_LENGTH)
    bigrams = Counter(f"{first} {second}" for first, second in pairwise(tokens))
    return (
        {f"w:{word}": _sublinear(count) for word, count in Counter(tokens).items()}
        | {f"p:{prefix}": _sublinear(count) for prefix, count in prefixes.items()}
        | {f"b:{pair}": BIGRAM_WEIGHT * _sublinear(count) for pair, count in bigrams.items()}
    )


def _bucket(feature: str) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode(), digest_size=_HASH_BYTES, person=_HASH_PERSON)
    value = int.from_bytes(digest.digest(), "big")
    return value % EMBEDDING_DIMENSIONS, -1.0 if value >> _SIGN_BIT else 1.0


def _embed(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for feature, weight in _features(text).items():
        index, sign = _bucket(feature)
        vector[index] += sign * weight
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if norm == 0.0:
        # No features, or features that cancel out. pgvector cannot compare a zero vector
        # by cosine, so such texts share one fixed unit vector.
        vector[_bucket(_EMPTY_TEXT_FEATURE)[0]] = 1.0
        return vector
    return [value / norm for value in vector]


@dataclass(frozen=True, slots=True)
class _Sample:
    """The readable parts of an analysis sample as plain text.

    Front matter, code blocks, HTML blocks and tables are left out; title is the one that
    the front matter gives, if any.
    """

    title: str | None
    headings: list[str]
    first_line: str | None
    paragraphs: list[str]


def _read_sample(sample: str) -> _Sample:
    lines = sample.splitlines()
    title, body_start = _front_matter(lines)
    headings: list[str] = []
    paragraphs: list[str] = []
    paragraph: list[str] = []
    first_line: str | None = None
    in_code_block = False
    for line in lines[body_start:]:
        if line.strip() == _EXCERPT_SEPARATOR_LINE:
            # Each excerpt is read on its own: one may end inside a code block it cut off.
            in_code_block = False
            _end_paragraph(paragraph, paragraphs)
            continue
        if _is_code_fence(line):
            in_code_block = not in_code_block
            _end_paragraph(paragraph, paragraphs)
            continue
        if in_code_block:
            continue
        if _MARKUP_LINE_RE.match(line):
            _end_paragraph(paragraph, paragraphs)
            continue
        heading = _heading_text(line)
        if heading is not None:
            _end_paragraph(paragraph, paragraphs)
            if text := _plain(heading):
                headings.append(text)
            continue
        text, is_list_item = _body_text(line)
        # A line without letters or digits ("---", "* * *") separates rather than says anything.
        has_content = _ALNUM_RE.search(text) is not None
        if is_list_item or not has_content:
            _end_paragraph(paragraph, paragraphs)
        if has_content:
            first_line = first_line or text
            paragraph.append(text)
    _end_paragraph(paragraph, paragraphs)
    return _Sample(title=title, headings=headings, first_line=first_line, paragraphs=paragraphs)


def _front_matter(lines: list[str]) -> tuple[str | None, int]:
    """The title in the front matter that the lines start with, and where the text begins.

    Without a closed front matter block, there is no title and the text begins at once.
    """
    if not lines or lines[0].rstrip() != _FRONT_MATTER_START:
        return None, 0
    for end in range(1, len(lines)):
        if lines[end].rstrip() in _FRONT_MATTER_ENDS:
            return _front_matter_title(lines[1:end]), end + 1
    return None, 0


def _front_matter_title(block: list[str]) -> str | None:
    """The value of a top-level "title" key that has a letter, without its quotes."""
    for line in block:
        key, colon, value = line.partition(":")
        if colon and key.rstrip().casefold() == _FRONT_MATTER_TITLE_KEY:
            title = " ".join(value.strip().strip(_QUOTES).split())
            return shorten(title, TITLE_MAX_LENGTH) if _has_letter(title) else None
    return None


def _end_paragraph(lines: list[str], paragraphs: list[str]) -> None:
    if lines:
        paragraphs.append(" ".join(lines))
        lines.clear()


def _is_code_fence(line: str) -> bool:
    stripped = line.lstrip(" ")
    return len(line) - len(stripped) <= _MARKDOWN_MAX_INDENT and stripped.startswith(_CODE_FENCES)


def _heading_text(line: str) -> str | None:
    """The text of a markdown heading line such as "## Title ##", or None for other lines.

    Plain string operations rather than a regex keep this linear on lines of many "#".
    """
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > _MARKDOWN_MAX_INDENT:
        return None
    level = len(stripped) - len(stripped.lstrip("#"))
    rest = stripped[level:]
    if not 1 <= level <= _MARKDOWN_MAX_HEADING_LEVEL or rest[:1] not in ("", " ", "\t"):
        return None
    text = rest.strip(" \t")
    # A closing run of "#" counts only after a space, so "C#" keeps its "#".
    without_closing = text.rstrip("#")
    if not without_closing or without_closing[-1] in " \t":
        text = without_closing.rstrip(" \t")
    return text


def _body_text(line: str) -> tuple[str, bool]:
    """A line's text without quote and list markers, and whether it starts a list item."""
    text = line.lstrip(" \t>")
    list_item = _LIST_ITEM_RE.match(text)
    if list_item:
        text = text[list_item.end() :]
    return _plain(text), list_item is not None


def _plain(text: str) -> str:
    unmarked = _INLINE_MARKUP_RE.sub(lambda match: match.group(1) or "", text)
    return " ".join(unmarked.split())


def _has_letter(text: str) -> bool:
    return _LETTER_RE.search(text) is not None


def _title(sample: _Sample, sentences: list[str], filename: str) -> str:
    """The document's title, taken from the first of these that it has.

    The title in its front matter, its first heading, a title-like first line, its first
    sentence and, last, its file name.
    """
    if sample.title is not None:
        return sample.title
    for heading in sample.headings:
        if _has_letter(heading):
            return shorten(heading, TITLE_MAX_LENGTH)
    line = sample.first_line
    if (
        line is not None
        and TITLE_LINE_MIN_CHARS <= len(line) <= TITLE_LINE_MAX_CHARS
        and _has_letter(line)
        and not line.endswith(_TITLE_LINE_ENDINGS)
    ):
        return line
    for sentence in sentences:
        if _has_letter(sentence):
            return shorten(sentence.rstrip(_SENTENCE_END_CHARS), TITLE_SENTENCE_MAX_CHARS)
    return _title_from_filename(filename)


def _title_from_filename(filename: str) -> str:
    stem = filename.rpartition(".")[0] or filename
    title = " ".join(stem.translate(_FILENAME_SEPARATORS).split())
    return shorten(title[:1].upper() + title[1:] if title else filename, TITLE_MAX_LENGTH)


def _summary(sentences: list[str]) -> str:
    """The first few sentences long enough to say something, else simply the first ones."""
    picked: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        key = sentence.casefold()
        if key in seen or not SUMMARY_MIN_WORDS <= len(words(sentence)) <= SUMMARY_MAX_WORDS:
            continue
        seen.add(key)
        picked.append(sentence)
        if len(picked) == SUMMARY_SENTENCES:
            break
    if not picked:
        picked = [sentence for sentence in sentences if _has_letter(sentence)][:SUMMARY_SENTENCES]
    return shorten(" ".join(_finished(sentence) for sentence in picked), SUMMARY_MAX_CHARS)


def _finished(sentence: str) -> str:
    """A sentence with a capital first letter and an ending: list items often lack both."""
    if sentence[-1].isalnum():
        sentence += "."
    return sentence[:1].upper() + sentence[1:]


def _topics(text: str) -> list[str]:
    """The most frequent content words, each in its most frequent form.

    Words are grouped by their first letters, so inflected forms count together.
    """
    groups: dict[str, Counter[str]] = {}
    for word, folded in _folded_words(text):
        if len(folded) < TOPIC_MIN_CHARS or _DIGIT_RE.search(folded):
            continue
        groups.setdefault(folded[:TOPIC_STEM_CHARS], Counter())[word.lower()] += 1
    # A stable sort keeps groups with equal counts in the order they first appeared.
    ranked = sorted(groups.values(), key=lambda forms: -forms.total())
    return [shorten(forms.most_common(1)[0][0], TOPIC_MAX_LENGTH) for forms in ranked[:TOPIC_COUNT]]


def _difficulty(sentences: list[str]) -> Difficulty:
    measured: list[list[str]] = []
    for sentence in sentences:
        lettered = [word for word in words(sentence) if _has_letter(word)]
        if len(lettered) >= READABILITY_MIN_WORDS:
            measured.append(lettered)
    all_words = [word for sentence_words in measured for word in sentence_words]
    if not all_words:
        return DEFAULT_DIFFICULTY
    syllables = sum(max(1, len(_VOWEL_GROUP_RE.findall(word))) for word in all_words)
    russian = 2 * sum(1 for word in all_words if has_cyrillic(word)) > len(all_words)
    sentence_weight, syllable_weight = FLESCH_WEIGHTS_RU if russian else FLESCH_WEIGHTS_EN
    reading_ease = (
        FLESCH_BASE
        - sentence_weight * len(all_words) / len(measured)
        - syllable_weight * syllables / len(all_words)
    )
    if reading_ease >= EASY_MIN_READING_EASE:
        return "easy"
    if reading_ease >= MEDIUM_MIN_READING_EASE:
        return "medium"
    return "hard"
