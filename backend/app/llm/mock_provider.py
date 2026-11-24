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

from app.documents.chunking import HEADING_SEPARATOR
from app.documents.text import (
    CHAT_STOPWORDS,
    ELLIPSIS,
    EXCERPT_SEPARATOR,
    NUMBER_WORDS,
    STOPWORDS_EN,
    STOPWORDS_FR,
    STOPWORDS_RU,
    has_cyrillic,
    shorten,
    split_sentences,
    word_matches,
    words,
)
from app.llm.base import (
    EMBEDDING_DIMENSIONS,
    AnalysisRequest,
    AnalysisResult,
    ChatContextPassage,
    ChatRequest,
    ChatResult,
    Difficulty,
)
from app.llm.schemas import TOPIC_MAX_LENGTH, ChatAnswer, DocumentAnalysis
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
# French stop words count only where titles and topics are picked, and number words ("two
# vectors", "ten minutes") only where topics are: the embeddings keep the words their stored
# vectors were made of.
_ALL_STOPWORDS: Final = _STOPWORDS | STOPWORDS_FR
_TOPIC_STOPWORDS: Final = _ALL_STOPWORDS | NUMBER_WORDS
_CHAT_MIN_KEYWORD_CHARS: Final = 2
_CHAT_MAX_QUERY_KEYWORDS: Final = 64
_CHAT_MAX_FOLLOWUP_KEYWORDS: Final = 32
_CHAT_FOLLOWUP_TRIGGER_KEYWORDS: Final = 2
_CHAT_FOLLOWUP_WEIGHT: Final = 0.6
_CHAT_EXACT_SCORE: Final = 2.0
_CHAT_PREFIX5_SCORE: Final = 1.5
_CHAT_PREFIX4_SCORE: Final = 1.2
_CHAT_PREFIX5_LEN: Final = 5
_CHAT_PREFIX4_LEN: Final = 4
_CHAT_PREFIX4_MAX_MIN_LEN: Final = 6
_CHAT_PREFIX4_MAX_LEN: Final = 7
_CHAT_COVERAGE_MIN_QUERY_KEYWORDS: Final = 3
_CHAT_COVERAGE_MIN_MATCHED: Final = 2
_CHAT_EXACT_LONG_MIN_LEN: Final = 5
_CHAT_HEADING_WEIGHT: Final = 0.35
_CHAT_MAX_ANSWER_SENTENCES: Final = 3
_CHAT_MAX_ANSWER_SOURCES: Final = 2
_CHAT_SENTENCE_MAX_CHARS: Final = 600
_CHAT_MAX_MARKER_STRIP_PASSES: Final = 8
_EMBEDDED_SOURCE_MARKER_RE: Final = re.compile(
    r"(?<![ \t])[ \t]++\[\s*+S\d{1,3}(?:\s*+[,;]\s*+S\d{1,3})*+\s*+\]"
    r"|\[\s*+S\d{1,3}(?:\s*+[,;]\s*+S\d{1,3})*+\s*+\]",
    re.IGNORECASE,
)
_CHAT_INSUFFICIENT_EN: Final = (
    "The uploaded materials do not contain enough information to answer this question."
)
_CHAT_INSUFFICIENT_RU: Final = (
    "В загруженных материалах недостаточно информации, чтобы ответить на этот вопрос."
)
# French articles and pronouns elided before a vowel: "l'algèbre", "d'une", "qu'il".
_ELIDED_WORDS: Final = frozenset(
    {"c", "d", "j", "l", "m", "n", "s", "t", "qu", "jusqu", "lorsqu", "puisqu"}
)

TITLE_LINE_MIN_CHARS: Final = 3
TITLE_LINE_MAX_CHARS: Final = 120
TITLE_SENTENCE_MAX_CHARS: Final = 80
SUMMARY_SENTENCES: Final = 3
SUMMARY_MIN_WORDS: Final = 6
SUMMARY_MAX_WORDS: Final = 60
SUMMARY_MAX_CHARS: Final = 600
TOPIC_COUNT: Final = 5
TOPIC_MAX_WORDS: Final = 3
# A word must be this long to be a topic of its own; inside a phrase a shorter one counts
# too, such as "баз" in "реляционных баз данных".
TOPIC_MIN_CHARS: Final = 4
TOPIC_PHRASE_WORD_MIN_CHARS: Final = 3
# A heading that the text comes back to, or a phrase that it repeats, occurs this often.
TOPIC_MIN_OCCURRENCES: Final = 2
# Forms of a word share their first letters, so they count together: "review", "reviews".
TOPIC_STEM_CHARS: Final = 6
# Topics whose words begin alike say the same thing: "нормальная форма", "нормальной форме".
TOPIC_SAME_WORD_CHARS: Final = 4
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
# A line of an HTML block, such as a centred logo, a row of a table or the definition of a
# link reference ("[docs]: https://…"): markup, not prose.
_MARKUP_LINE_RE: Final = re.compile(r"[ \t]*+(?:<[A-Za-z/!]|\||\[[^\[\]]*+\]:)")
_EXCERPT_SEPARATOR_LINE: Final = EXCERPT_SEPARATOR.strip()
_TITLE_LINE_ENDINGS: Final = (".", "!", "?", "…", ":", ";", ",")
_SENTENCE_END_CHARS: Final = ".!?…"
_CLOSING_MARKS: Final = "\"'»”’)]"
_OPENING_MARKS: Final = "\"'«“‘(["
_LETTER_RE: Final = re.compile(r"[^\W\d_]")
_ALNUM_RE: Final = re.compile(r"[^\W_]")
_DIGIT_RE: Final = re.compile(r"\d")
_VOWEL_GROUP_RE: Final = re.compile(r"[aeiouyаеёиоуыэюя]++", re.IGNORECASE)
# Markdown list markers and the bullets that text extracted from PDF slides starts lines with.
# Dashes are left out: in wrapped text a line may start with a dash mid-sentence.
_LIST_ITEM_RE: Final = re.compile(r"(?:[-*+•◦▪‣]|\d{1,9}[.)])[ \t]++")
# Where an image or a badge leads: an address in parentheses, or a reference in brackets
# that a definition elsewhere in the text gives the address of.
_IMAGE_TARGET: Final = r"(?:\([^()\s]*+\)|\[[^\[\]]*+\])"
# Markup is dropped as a reader of the rendered text would not see it. Code spans keep their
# text as it is, tags and marks included. Images go, and badges with them, which are images
# inside links; other links keep their text. HTML tags and comments go and the text between
# them stays, while an address in angle brackets is a link that shows itself. Stray
# backticks go, and so do runs of emphasis marks at the edges of words, while those inside
# words (snake_case, 2*3, x**2) stay. A run of marks can match only from its first mark: "_"
# is a word character, so without that anchor a run between two letters would be scanned
# again from each of its marks.
_INLINE_MARKUP_RE: Final = re.compile(
    rf"`([^`]++)`|\[!\[[^\[\]]*+\]{_IMAGE_TARGET}\]{_IMAGE_TARGET}"
    rf"|!\[[^\[\]]*+\]{_IMAGE_TARGET}|\[([^\[\]]*+)\]\([^()\s]*+\)"
    r"|</?([A-Za-z][A-Za-z0-9-]*+)(?:[\s/][^<>]*+)?>|<![^<>]*+>"
    r"|`++|(?<![\w*~])[*_~]++|(?<![*_~])[*_~]++(?!\w)"
)
# Tags that break the line or stand apart from the text around them leave a space; other
# tags, such as those of H<sub>2</sub>O, leave the letters on both sides together.
_SPACING_TAGS: Final = frozenset({"br", "hr", "img", "p", "div", "li"})
# A web address names no topic, although its parts look like words; it ends a phrase as
# punctuation does.
_WEB_ADDRESS_RE: Final = re.compile(r"\b(?:https?://|www\.)\S++", re.IGNORECASE)
_FILENAME_SEPARATORS: Final = str.maketrans("_.-", "   ")

# A phrase of a topic, by the stems of its words, which its inflected forms share.
type _Phrase = tuple[str, ...]


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
    """Offline heuristic document analysis and grounded extractive Q&A."""

    @property
    def model_name(self) -> str:
        return MOCK_ANALYSIS_MODEL

    def analyze_document(self, request: AnalysisRequest) -> AnalysisResult:
        sample = _read_sample(request.sample)
        sentences = [
            sentence for paragraph in sample.paragraphs for sentence in split_sentences(paragraph)
        ]
        title = _title(sample, sentences, request.filename)
        headings = [*request.outline.splitlines(), *sample.headings]
        analysis = DocumentAnalysis(
            title=title,
            summary=_summary(sentences),
            topics=_topics(headings, sample.paragraphs) or [shorten(title, TOPIC_MAX_LENGTH)],
            difficulty=_difficulty(sentences),
        )
        return AnalysisResult(
            analysis=analysis, model=MOCK_ANALYSIS_MODEL, prompt_tokens=0, completion_tokens=0
        )

    def answer_question(
        self, request: ChatRequest, *, timeout_budget_seconds: float | None = None
    ) -> ChatResult:
        _ = timeout_budget_seconds
        answer = _answer_chat(request)
        return ChatResult(
            answer=answer, model=MOCK_ANALYSIS_MODEL, prompt_tokens=0, completion_tokens=0
        )


def _fold(word: str) -> str:
    """The form words are compared in: NFKC, case-folded, ё as е and ’ as an apostrophe."""
    return unicodedata.normalize("NFKC", word).casefold().replace("ё", "е").replace("’", "'")


def _folded_words(text: str) -> Iterator[tuple[str, str]]:
    """Each word of a text with its folded form, stop words and overlong runs left out.

    Words are folded one at a time: CPython grows the NFKC result a few characters at a
    time, which is quadratic on a long run that expands, such as "…" turning into "...".
    """
    for word in words(_composed(text)):
        if len(word) <= TOKEN_MAX_CHARS and (folded := _fold(word)) not in _STOPWORDS:
            yield word, folded


def _composed(text: str) -> str:
    """The text composed to NFC piece by piece, with one space between its pieces.

    A combining mark is not a word character, so without this "ё" written as "е" and a
    diaeresis would split its word in two.
    """
    return " ".join(
        unicodedata.normalize("NFC", piece) if len(piece) <= _PIECE_MAX_CHARS else piece
        for piece in text.split()
    )


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
        # No features, or features that cancel out. pgvector cannot compare a zero vector by
        # cosine, so the text itself picks the one component it sets: two such texts are
        # alike only when they are the same text, spaces aside, or their hashes happen to
        # pick the same component. Such texts once shared one component; as only their
        # vectors changed, the model name stays: a stored one keeps that component, which a
        # query now sets only by a hash collision.
        vector[_bucket(_EMPTY_TEXT_FEATURE + " ".join(text.split()))[0]] = 1.0
        return vector
    return [value / norm for value in vector]


@dataclass(frozen=True, slots=True)
class _Sample:
    """The readable parts of an analysis sample as plain text.

    Front matter, code blocks, HTML blocks and tables are left out. title is the title the
    text gives itself: the one in its front matter, or its first lines when they stand
    alone like a title and nothing else names the text. Those lines head the text rather
    than start it, so they count among its headings and not its paragraphs, unless they are
    all the text there is.
    """

    title: str | None
    headings: list[str]
    paragraphs: list[str]


def _read_sample(sample: str) -> _Sample:
    lines = sample.splitlines()
    title, body_start = _front_matter(lines)
    headings: list[str] = []
    # A paragraph is kept as its lines until the end, so its first lines can still be told
    # from the rest.
    paragraphs: list[list[str]] = []
    paragraph: list[str] = []
    starts_with_list_item = False
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
            if not (paragraphs or paragraph):
                starts_with_list_item = is_list_item
            paragraph.append(text)
    _end_paragraph(paragraph, paragraphs)
    if not starts_with_list_item:
        title = _take_title_lines(paragraphs, headings, title)
    return _Sample(
        title=title,
        headings=headings,
        paragraphs=[" ".join(paragraph_lines) for paragraph_lines in paragraphs],
    )


def _take_title_lines(
    paragraphs: list[list[str]], headings: list[str], title: str | None
) -> str | None:
    """The text's title, once the first lines that stand alone like a title are taken out.

    With nothing else naming the text, those lines become its title and its first heading.
    Lines that only repeat the name that its front matter or its first heading gives go.
    Lines that are all the text there is stay its text, and its title as well.
    """
    count = _title_line_count(paragraphs[0]) if paragraphs else 0
    if not count:
        return title
    title_line = " ".join(paragraphs[0][:count])
    name = title or next((heading for heading in headings if _has_letter(heading)), None)
    if name is not None and title_line.casefold() != name.casefold():
        # The text has a name already, so these lines start it: they run on in their
        # paragraph, as Markdown renders them.
        return title
    if count < len(paragraphs[0]) or len(paragraphs) > 1:
        del paragraphs[0][:count]
        if not paragraphs[0]:
            del paragraphs[0]
        if name is None:
            headings.insert(0, title_line)
    return title_line if name is None else title


def _title_line_count(lines: list[str]) -> int:
    """How many first lines of a paragraph stand alone like a title, or 0 if they do not.

    A PDF's title has no blank line under it and may take two lines, so the candidates are
    the lines before the first one that starts a sentence, or all of them.
    """
    count = 0
    length = 0
    for line in lines:
        if count and _starts_sentence(line):
            break
        # The lines are read as one, with a space between each two.
        length += len(line) + (1 if count else 0)
        if length > TITLE_LINE_MAX_CHARS:
            return 0
        count += 1
    return count if _is_title_like(" ".join(lines[:count])) else 0


def _starts_sentence(text: str) -> bool:
    """Whether the text starts like a sentence: with a capital or a digit, maybe quoted."""
    first = text.lstrip(_OPENING_MARKS)[:1]
    return first.isupper() or first.isdigit()


def _is_title_like(text: str) -> bool:
    """Whether text could be a title: short, with a letter and ending as a title does.

    Text ending in punctuation ends a sentence or a clause, and text ending in a stop word,
    such as "by" or "и", is a sentence that goes on in the next line. The last word is all
    that follows the last space, so an address such as "example.org/courses/it" does not end
    in a stop word.
    """
    if not (TITLE_LINE_MIN_CHARS <= len(text) <= TITLE_LINE_MAX_CHARS and _has_letter(text)):
        return False
    last_word = text.rsplit(maxsplit=1)[-1]
    return not text.endswith(_TITLE_LINE_ENDINGS) and _fold(last_word) not in _ALL_STOPWORDS


def _front_matter(lines: list[str]) -> tuple[str | None, int]:
    """The title in the front matter that the lines start with, and where the text begins.

    Front matter is lines of YAML between a first line "---" and a line "---" or "...", or
    the separator of an excerpt that cut it short. Without it, as when a thematic break
    stands above a paragraph, there is no title and the text begins at once.
    """
    if not lines or lines[0].rstrip() != _FRONT_MATTER_START:
        return None, 0
    for end in range(1, len(lines)):
        line = lines[end].rstrip()
        if line in _FRONT_MATTER_ENDS:
            return _front_matter_title(lines[1:end]), end + 1
        if line.strip() == _EXCERPT_SEPARATOR_LINE:
            return _front_matter_title(lines[1:end]), end
        if not _is_front_matter_line(line):
            break
    return None, 0


def _is_front_matter_line(line: str) -> bool:
    """Whether a line can be one of front matter: blank, indented, a list item or a key."""
    key, colon, _ = line.partition(":")
    return not line.strip() or line.startswith((" ", "\t", "- ")) or bool(colon and key.strip())


def _front_matter_title(block: list[str]) -> str | None:
    """The value of a top-level "title" key that has a letter, without its quotes."""
    for line in block:
        key, colon, value = line.partition(":")
        if colon and key.rstrip().casefold() == _FRONT_MATTER_TITLE_KEY:
            title = " ".join(value.strip().strip(_QUOTES).split())
            return shorten(title, TITLE_MAX_LENGTH) if _has_letter(title) else None
    return None


def _end_paragraph(lines: list[str], paragraphs: list[list[str]]) -> None:
    if lines:
        paragraphs.append(lines.copy())
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
    return " ".join(_INLINE_MARKUP_RE.sub(_shown_text, text).split())


def _shown_text(markup: re.Match[str]) -> str:
    """What a reader sees of a piece of inline markup.

    That is the text of a code span or a link, a space for a tag that breaks the line, and
    nothing of the rest.
    """
    code, link_text, tag = markup.groups()
    if code is not None:
        return code
    if link_text is not None:
        return link_text
    return " " if tag is not None and tag.casefold() in _SPACING_TAGS else ""


def _has_letter(text: str) -> bool:
    return _LETTER_RE.search(text) is not None


def _title(sample: _Sample, sentences: list[str], filename: str) -> str:
    """The document's title, taken from the first of these that it has.

    The title it gives itself in its front matter or its first lines, its first heading,
    its first sentence and, last, its file name.
    """
    if sample.title is not None:
        return sample.title
    for heading in sample.headings:
        if _has_letter(heading):
            return shorten(heading, TITLE_MAX_LENGTH)
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


def _topics(headings: Sequence[str], paragraphs: Sequence[str]) -> list[str]:
    """Up to TOPIC_COUNT topics, each a phrase of up to TOPIC_MAX_WORDS words in lower case.

    First come the headings that the document comes back to, then the phrases it repeats,
    by occurrences times words, then its most frequent words; stable sorts keep ties in the
    order they first appeared. A phrase or a word that only ever occurs as a part of one
    longer repeated phrase is left to that phrase.
    """
    headings = list(dict.fromkeys(headings))
    heading_counts: Counter[_Phrase] = Counter()
    text_counts: Counter[_Phrase] = Counter()
    forms: dict[_Phrase, Counter[str]] = {}
    for heading in headings:
        _count_phrases(heading, heading_counts, forms)
    for paragraph in paragraphs:
        _count_phrases(paragraph, text_counts, forms)
    counts = heading_counts + text_counts
    within: Counter[_Phrase] = Counter()
    for phrase, count in counts.items():
        if len(phrase) > 1 and count >= TOPIC_MIN_OCCURRENCES:
            for part in (phrase[:-1], phrase[1:]):
                within[part] = max(within[part], count)
    labels: dict[_Phrase, str] = {}
    for heading in headings:
        runs = list(_topic_runs(heading))
        if len(runs) == 1 and len(runs[0]) <= TOPIC_MAX_WORDS:
            phrase = tuple(stem for _, stem in runs[0])
            if counts[phrase] >= TOPIC_MIN_OCCURRENCES:
                labels.setdefault(phrase, " ".join(word for word, _ in runs[0]))
    standalone = [p for p in counts if p in text_counts and within[p] < counts[p]]
    candidates = [
        *sorted(labels, key=lambda phrase: -counts[phrase]),
        *sorted(
            (p for p in standalone if len(p) > 1 and counts[p] >= TOPIC_MIN_OCCURRENCES),
            key=lambda phrase: -counts[phrase] * len(phrase),
        ),
        *sorted(
            (p for p in standalone if len(p) == 1 and len(p[0]) >= TOPIC_MIN_CHARS),
            key=lambda phrase: -counts[phrase],
        ),
    ]
    return _distinct_topics(candidates, labels, forms)


def _count_phrases(text: str, counts: Counter[_Phrase], forms: dict[_Phrase, Counter[str]]) -> None:
    """Count every phrase of up to TOPIC_MAX_WORDS words of the text, and its forms."""
    for run in _topic_runs(text):
        for size in range(1, TOPIC_MAX_WORDS + 1):
            for start in range(len(run) - size + 1):
                words_of_phrase = run[start : start + size]
                phrase = tuple(stem for _, stem in words_of_phrase)
                counts[phrase] += 1
                form = " ".join(word for word, _ in words_of_phrase)
                forms.setdefault(phrase, Counter())[form] += 1


def _topic_runs(text: str) -> Iterator[list[tuple[str, str]]]:
    """The runs of words that topics are made of, each word in lower case with its stem.

    A stop word, a number, a word with a digit, a word too short or too long, punctuation
    and a web address all end a run.
    """
    composed = _composed(_WEB_ADDRESS_RE.sub(",", text))
    run: list[tuple[str, str]] = []
    end = 0
    for match in word_matches(composed):
        if run and not composed[end : match.start()].isspace():
            yield run
            run = []
        end = match.end()
        word = _without_elision(match.group())
        # A longer run is no word and stays unfolded: NFKC is quadratic on a long run.
        folded = _fold(word) if len(word) <= TOKEN_MAX_CHARS else ""
        if (
            folded in _TOPIC_STOPWORDS
            or not TOPIC_PHRASE_WORD_MIN_CHARS <= len(folded) <= TOKEN_MAX_CHARS
            or _DIGIT_RE.search(folded)
        ):
            if run:
                yield run
                run = []
        else:
            run.append((word.lower(), folded[:TOPIC_STEM_CHARS]))
    if run:
        yield run


def _without_elision(word: str) -> str:
    """The word without a French article or pronoun elided before it: "l'algèbre" is "algèbre"."""
    elided, apostrophe, rest = word.replace("’", "'").partition("'")
    return rest if apostrophe and elided.casefold() in _ELIDED_WORDS else word


def _distinct_topics(
    candidates: Sequence[_Phrase], labels: dict[_Phrase, str], forms: dict[_Phrase, Counter[str]]
) -> list[str]:
    """The first candidates that say something new, at most TOPIC_COUNT of them.

    A candidate says nothing new when most of its words begin like the words of a topic
    already taken, as the overlapping phrases of a longer repeated term do, or when it
    holds all of one's words. Each is written as its heading writes it, else in its most
    frequent form.
    """
    topics: list[str] = []
    taken: list[frozenset[str]] = []
    for phrase in candidates:
        beginnings = frozenset(stem[:TOPIC_SAME_WORD_CHARS] for stem in phrase)
        if any(
            2 * len(beginnings & other) > len(beginnings) or other <= beginnings for other in taken
        ):
            continue
        label = labels.get(phrase) or forms[phrase].most_common(1)[0][0]
        topics.append(shorten(label, TOPIC_MAX_LENGTH))
        taken.append(beginnings)
        if len(topics) == TOPIC_COUNT:
            break
    return topics


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


@dataclass(frozen=True, slots=True)
class _QueryIndex:
    weights: dict[str, float]
    prefix5: dict[str, tuple[str, ...]]
    prefix4_le6: dict[str, tuple[str, ...]]
    prefix4_len7: dict[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _TokenMatch:
    matched: dict[str, float]
    has_exact_long: bool


@dataclass(frozen=True, slots=True)
class _CandidateSentence:
    source_index: int
    source_label: str
    sentence_index: int
    text: str
    score: float
    sentence_score: float
    is_question: bool


def _answer_chat(request: ChatRequest) -> ChatAnswer:
    """Deterministic extractive grounded Q&A across retrieved passages."""
    if not request.sources:
        return _insufficient_chat_answer(request.question)
    query = _build_query_index(request)
    if query is None:
        return _insufficient_chat_answer(request.question)
    candidates: list[_CandidateSentence] = []
    for source_index, source in enumerate(request.sources):
        candidates.extend(_score_source(query, source_index, source))
    picked = _select_candidates(candidates)
    if not picked:
        return _insufficient_chat_answer(request.question)
    return _render_chat_answer(picked)


def _insufficient_chat_answer(question: str) -> ChatAnswer:
    message = _CHAT_INSUFFICIENT_RU if has_cyrillic(question) else _CHAT_INSUFFICIENT_EN
    return ChatAnswer(answer=message, citations=[], insufficient_context=True)


def _build_query_index(request: ChatRequest) -> _QueryIndex | None:
    primary = _chat_keywords(request.question, limit=_CHAT_MAX_QUERY_KEYWORDS)
    weights: dict[str, float] = dict.fromkeys(primary, 1.0)
    if len(primary) < _CHAT_FOLLOWUP_TRIGGER_KEYWORDS:
        for turn in reversed(request.history):
            if turn.role != "user":
                continue
            prior = _chat_keywords(turn.content, limit=_CHAT_MAX_FOLLOWUP_KEYWORDS)
            if prior:
                for keyword in prior:
                    weights.setdefault(keyword, _CHAT_FOLLOWUP_WEIGHT)
                break
    if not weights:
        return None
    prefix5: dict[str, list[str]] = {}
    prefix4_le6: dict[str, list[str]] = {}
    prefix4_len7: dict[str, list[str]] = {}
    for keyword in weights:
        length = len(keyword)
        if length >= _CHAT_PREFIX5_LEN:
            prefix5.setdefault(keyword[:_CHAT_PREFIX5_LEN], []).append(keyword)
        if _CHAT_PREFIX4_LEN <= length <= _CHAT_PREFIX4_MAX_MIN_LEN:
            prefix4_le6.setdefault(keyword[:_CHAT_PREFIX4_LEN], []).append(keyword)
        elif length == _CHAT_PREFIX4_MAX_LEN:
            prefix4_len7.setdefault(keyword[:_CHAT_PREFIX4_LEN], []).append(keyword)
    return _QueryIndex(
        weights=weights,
        prefix5={key: tuple(values) for key, values in prefix5.items()},
        prefix4_le6={key: tuple(values) for key, values in prefix4_le6.items()},
        prefix4_len7={key: tuple(values) for key, values in prefix4_len7.items()},
    )


def _chat_keywords(text: str, *, limit: int) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for match in word_matches(_composed(text)):
        word = match.group()
        if len(word) > TOKEN_MAX_CHARS:
            continue
        folded = _fold(word)
        if len(folded) < _CHAT_MIN_KEYWORD_CHARS or folded in CHAT_STOPWORDS or folded in seen:
            continue
        seen.add(folded)
        keywords.append(folded)
        if len(keywords) == limit:
            break
    return keywords


def _chat_token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in word_matches(_composed(text)):
        word = match.group()
        if len(word) > TOKEN_MAX_CHARS:
            continue
        folded = _fold(word)
        if len(folded) >= _CHAT_MIN_KEYWORD_CHARS and folded not in CHAT_STOPWORDS:
            tokens.add(folded)
    return tokens


def _match_tokens(query: _QueryIndex, tokens: set[str]) -> _TokenMatch:
    matched: dict[str, float] = {}
    has_exact_long = False
    for token in tokens:
        if token in query.weights:
            matched[token] = _CHAT_EXACT_SCORE
            if len(token) >= _CHAT_EXACT_LONG_MIN_LEN:
                has_exact_long = True
        length = len(token)
        if length >= _CHAT_PREFIX5_LEN:
            for keyword in query.prefix5.get(token[:_CHAT_PREFIX5_LEN], ()):
                if matched.get(keyword, 0.0) < _CHAT_PREFIX5_SCORE:
                    matched[keyword] = _CHAT_PREFIX5_SCORE
        if _CHAT_PREFIX4_LEN <= length <= _CHAT_PREFIX4_MAX_MIN_LEN:
            prefix = token[:_CHAT_PREFIX4_LEN]
            for keyword in (
                *query.prefix4_le6.get(prefix, ()),
                *query.prefix4_len7.get(prefix, ()),
            ):
                if matched.get(keyword, 0.0) < _CHAT_PREFIX4_SCORE:
                    matched[keyword] = _CHAT_PREFIX4_SCORE
        elif length == _CHAT_PREFIX4_MAX_LEN:
            for keyword in query.prefix4_le6.get(token[:_CHAT_PREFIX4_LEN], ()):
                if matched.get(keyword, 0.0) < _CHAT_PREFIX4_SCORE:
                    matched[keyword] = _CHAT_PREFIX4_SCORE
    return _TokenMatch(matched=matched, has_exact_long=has_exact_long)


def _score_source(
    query: _QueryIndex, source_index: int, source: ChatContextPassage
) -> list[_CandidateSentence]:
    heading_match = _match_tokens(query, _chat_token_set(source.heading or ""))
    heading_score = sum(
        tier * query.weights[keyword] for keyword, tier in heading_match.matched.items()
    )
    heading_only_ok = len(heading_match.matched) >= min(
        len(query.weights), _CHAT_COVERAGE_MIN_MATCHED
    )
    needs_coverage = len(query.weights) >= _CHAT_COVERAGE_MIN_QUERY_KEYWORDS
    candidates: list[_CandidateSentence] = []
    for sentence_index, sentence in enumerate(
        _source_sentences(source.content, heading=source.heading)
    ):
        sentence_match = _match_tokens(query, _chat_token_set(sentence))
        sentence_score = sum(
            tier * query.weights[keyword] for keyword, tier in sentence_match.matched.items()
        )
        if sentence_score == 0.0 and not heading_only_ok:
            continue
        combined_count = len(sentence_match.matched.keys() | heading_match.matched.keys())
        has_exact_long = sentence_match.has_exact_long or (
            sentence_score > 0.0 and heading_match.has_exact_long
        )
        if needs_coverage and combined_count < _CHAT_COVERAGE_MIN_MATCHED and not has_exact_long:
            continue
        total_score = sentence_score + _CHAT_HEADING_WEIGHT * heading_score
        if total_score <= 0.0:
            continue
        candidates.append(
            _CandidateSentence(
                source_index=source_index,
                source_label=source.label,
                sentence_index=sentence_index,
                text=sentence,
                score=total_score,
                sentence_score=sentence_score,
                is_question=sentence.endswith("?"),
            )
        )
    return candidates


@dataclass(frozen=True, slots=True)
class _FenceLine:
    index: int
    marker: str
    length: int
    has_info: bool


def _parse_code_fence(index: int, line: str) -> _FenceLine | None:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > _MARKDOWN_MAX_INDENT or not stripped.startswith(_CODE_FENCES):
        return None
    marker = stripped[0]
    length = len(stripped) - len(stripped.lstrip(marker))
    rest = stripped[length:].strip()
    if marker == "`" and "`" in rest:
        return None
    return _FenceLine(index=index, marker=marker, length=length, has_info=bool(rest))


def _code_block_mask(lines: Sequence[str]) -> list[bool]:
    """Suppress fence lines and lines inside paired code blocks only.

    A chunk cut mid-code-block may begin with a lone closing fence; leaving unpaired fences
    open avoids discarding all subsequent prose.
    """
    suppressed = [False] * len(lines)
    open_fence: _FenceLine | None = None
    for index, line in enumerate(lines):
        fence = _parse_code_fence(index, line)
        if fence is None:
            continue
        suppressed[index] = True
        if open_fence is None:
            open_fence = fence
        elif (
            not fence.has_info
            and fence.marker == open_fence.marker
            and fence.length >= open_fence.length
        ):
            for body_index in range(open_fence.index + 1, fence.index):
                suppressed[body_index] = True
            open_fence = None
        elif fence.has_info:
            open_fence = fence
    return suppressed


def _strip_embedded_source_markers(text: str) -> str:
    """Strip embedded [S...] markers in bounded passes so nested tags cannot stitch together."""
    cleaned = text
    for _ in range(_CHAT_MAX_MARKER_STRIP_PASSES):
        updated = _EMBEDDED_SOURCE_MARKER_RE.sub("", cleaned)
        if updated == cleaned:
            return " ".join(cleaned.split())
        cleaned = updated
    if _EMBEDDED_SOURCE_MARKER_RE.search(cleaned) is not None:
        cleaned = _EMBEDDED_SOURCE_MARKER_RE.sub(ELLIPSIS, cleaned)
    return " ".join(cleaned.split())


def _heading_name_set(heading: str | None) -> set[str]:
    if not heading:
        return set()
    names = {heading.strip().casefold()}
    for part in heading.split(HEADING_SEPARATOR):
        stripped = part.strip()
        if stripped:
            names.add(stripped.casefold())
    return names


def _flush_source_paragraph(
    paragraph: list[str],
    *,
    is_list_item: bool,
    heading_names: set[str],
    sentences: list[str],
) -> None:
    if not paragraph:
        return
    lines = paragraph.copy()
    paragraph.clear()
    if not is_list_item:
        count = _title_line_count(lines)
        if count > 0:
            candidate = " ".join(lines[:count])
            if count == len(lines) or candidate.casefold() in heading_names:
                del lines[:count]
        if not lines:
            return
    joined = _strip_embedded_source_markers(" ".join(lines))
    if not joined or _ALNUM_RE.search(joined) is None:
        return
    for sentence in split_sentences(joined):
        stripped = sentence.strip()
        if stripped and _ALNUM_RE.search(stripped) is not None:
            sentences.append(_finished(stripped) if is_list_item else stripped)


def _source_sentences(content: str, *, heading: str | None = None) -> list[str]:
    lines = content.splitlines()
    suppressed = _code_block_mask(lines)
    heading_names = _heading_name_set(heading)
    sentences: list[str] = []
    paragraph: list[str] = []
    in_list_item = False
    for raw_line, is_code in zip(lines, suppressed, strict=True):
        if is_code or _MARKUP_LINE_RE.match(raw_line):
            _flush_source_paragraph(
                paragraph,
                is_list_item=in_list_item,
                heading_names=heading_names,
                sentences=sentences,
            )
            in_list_item = False
            continue
        heading_line = _heading_text(raw_line)
        if heading_line is not None:
            _flush_source_paragraph(
                paragraph,
                is_list_item=in_list_item,
                heading_names=heading_names,
                sentences=sentences,
            )
            in_list_item = False
            if plain_heading := _plain(heading_line):
                heading_names.add(plain_heading.casefold())
            continue
        cleaned, starts_list = _body_text(raw_line)
        cleaned = _strip_embedded_source_markers(cleaned)
        if not cleaned or _ALNUM_RE.search(cleaned) is None:
            _flush_source_paragraph(
                paragraph,
                is_list_item=in_list_item,
                heading_names=heading_names,
                sentences=sentences,
            )
            in_list_item = False
            continue
        if starts_list:
            _flush_source_paragraph(
                paragraph,
                is_list_item=in_list_item,
                heading_names=heading_names,
                sentences=sentences,
            )
            in_list_item = True
        paragraph.append(cleaned)
    _flush_source_paragraph(
        paragraph,
        is_list_item=in_list_item,
        heading_names=heading_names,
        sentences=sentences,
    )
    return sentences


def _select_candidates(candidates: Sequence[_CandidateSentence]) -> list[_CandidateSentence]:
    if not candidates:
        return []
    direct = [item for item in candidates if item.sentence_score > 0.0]
    pool = direct if direct else list(candidates)
    declarative = [item for item in pool if not item.is_question]
    ranked = sorted(
        declarative if declarative else pool,
        key=lambda item: (
            -item.score,
            -item.sentence_score,
            item.source_index,
            item.sentence_index,
        ),
    )
    picked: list[_CandidateSentence] = []
    seen_text: set[str] = set()
    chosen_sources: set[str] = set()
    for item in ranked:
        key = _fold(shorten(item.text, _CHAT_SENTENCE_MAX_CHARS))
        if key in seen_text:
            continue
        if (
            item.source_label not in chosen_sources
            and len(chosen_sources) >= _CHAT_MAX_ANSWER_SOURCES
        ):
            continue
        seen_text.add(key)
        chosen_sources.add(item.source_label)
        picked.append(item)
        if len(picked) == _CHAT_MAX_ANSWER_SENTENCES:
            break
    return picked


def _render_chat_answer(picked: Sequence[_CandidateSentence]) -> ChatAnswer:
    source_order: list[str] = []
    by_source: dict[str, list[_CandidateSentence]] = {}
    for item in picked:
        if item.source_label not in by_source:
            source_order.append(item.source_label)
            by_source[item.source_label] = []
        by_source[item.source_label].append(item)
    parts: list[str] = []
    for label in source_order:
        ordered = sorted(by_source[label], key=lambda item: item.sentence_index)
        text = " ".join(_finished(shorten(item.text, _CHAT_SENTENCE_MAX_CHARS)) for item in ordered)
        parts.append(f"{text} [{label}]")
    return ChatAnswer(
        answer=" ".join(parts),
        citations=source_order,
        insufficient_context=False,
    )
