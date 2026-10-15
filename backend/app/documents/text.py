"""Word, sentence and stop-word helpers shared by chunking, statistics and offline analysis.

Every pattern here runs on untrusted document text, so each one must stay linear on hostile
input such as two million dots.
"""

# ruff: noqa: RUF001, RUF003 -- Cyrillic letters and typographic quotes are meant

import re
from typing import Final


def _word_set(text: str) -> frozenset[str]:
    return frozenset(text.split())


ELLIPSIS: Final = "…"

# Letters and digits of any script; a hyphen or an apostrophe counts only between two of
# them ("из-за", "don't"), so dashes and quotes around a word stay outside it.
_WORD_RE: Final = re.compile(r"[^\W_]++(?:[-'’][^\W_]++)*+")
# A run of terminal punctuation with any closing quotes or brackets, then whitespace and a
# capital letter or a digit, possibly behind an opening quote or bracket. The lookbehind
# lets a match start only where a run starts and the possessive quantifiers never give
# characters back, so a long run is scanned once instead of once per character.
_SENTENCE_END_RE: Final = re.compile(
    r"""(?<![.!?…])([.!?…]++["'»”’)\]]*+)\s+(?=["'«“‘(\[]?[A-ZА-ЯЁ0-9])"""
)
_CLOSING_MARKS: Final = "\"'»”’)]"
_WORD_EDGE_MARKS: Final = "\"'«»“”‘’()[]"
# Long enough for the longest abbreviation together with the word before it.
_ABBREVIATION_WINDOW: Final = 32
# Abbreviations that a capitalised word or a number often follows inside a sentence
# ("Dr. Watson", "e.g. Python", "см. рис. 2"). Ones that usually close a list ("etc.",
# "и др.", "т.д.") are left out, so a capital letter after them starts a new sentence.
_ABBREVIATIONS: Final = _word_set(
    """
    al approx apr aug ca capt cf ch chap col dec dr e.g ed eds eq eqs feb fig figs gen i.e jan
    jr jul jun lt mr mrs ms no nos nov oct pp prof ref refs rev sec sep sept sgt sr st viz vol
    vols vs акад англ вв вып гг гл греч доц изд им кв лат напр нем обл пер пп просп проф разд
    ред рис см ср ст стр т.е т.к т.н табл тел тыс ул франц
    """
)
# A single letter is an initial ("А. С. Пушкин") or part of an abbreviation such as
# "т. е."; only "т. д." and "т. п." close a list and so may end a sentence.
_LIST_END_PREFIX: Final = "т."
_LIST_END_LETTERS: Final = frozenset({"д", "п"})
_CYRILLIC_RE: Final = re.compile(r"[А-Яа-яЁё]")
# Separators that would dangle before an ellipsis.
_TRAILING_SEPARATORS: Final = " \t\r\n,;:-–—"

# Lower case, with ё written as е: the form tokens are compared in.
STOPWORDS_EN: Final = _word_set(
    """
    a about above after again against all also am an and any are aren't as at be because been
    before being below between both but by can can't cannot could couldn't did didn't do does
    doesn't doing don't down during each either even every few for from further had hadn't has
    hasn't have haven't having he he'd he'll he's her here here's hers herself him himself his
    how how's however i i'd i'll i'm i've if in into is isn't it it's its itself just let's many
    may me might more most much must mustn't my myself neither no nor not of off often on once
    one only or other ought our ours ourselves out over own same shall shan't she she'd she'll
    she's should shouldn't since so some such than that that's the their theirs them themselves
    then there there's therefore these they they'd they'll they're they've this those though
    through thus to too under until up upon us very via was wasn't we we'd we'll we're we've
    well were weren't what what's when when's where where's whether which while who who's whom
    whose why why's will with within without won't would wouldn't yet you you'd you'll you're
    you've your yours yourself yourselves
    """
)
STOPWORDS_RU: Final = _word_set(
    """
    а без более бы был была были было быть в вам вас ведь весь во вот впрочем все всегда всего
    всех всю вы где да даже для до другой его ее ей ему если есть еще ж же за зачем здесь и из
    из-за или им иногда их к каждый как какая какой когда конечно которая которого которое
    которой котором которую которые который которых кроме кто куда ли лучше между меня мне много
    может можно мой моя мы на над надо наконец например нас не него нее ней нельзя нет ни нибудь
    никогда ним них ничего но ну о об один однако он она они оно опять от перед по под после
    потом потому почти поэтому при про раз разве с сам свое свои свой свою себе себя сейчас со
    совсем так также такой там тебя тем теперь то тогда того тоже только том тот три тут ты у уж
    уже хорошо хоть чего чем через что чтоб чтобы чуть эта эти этим этих это этого этой этом
    этот эту я является являются
    """
)


def words(text: str) -> list[str]:
    """The words of a text in reading order: runs of letters and digits of any script."""
    return _WORD_RE.findall(text)


def split_sentences(text: str) -> list[str]:
    """Split text into trimmed sentences; a closing quote or bracket stays with its sentence."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        single_period = match.group(1).rstrip(_CLOSING_MARKS) == "."
        if single_period and _is_abbreviation(text, match.start()):
            continue
        if sentence := text[start : match.end(1)].strip():
            sentences.append(sentence)
        start = match.end()
    if tail := text[start:].strip():
        sentences.append(tail)
    return sentences


def _is_abbreviation(text: str, period: int) -> bool:
    """Whether the period at text[period] closes an initial or a known abbreviation."""
    tokens = text[max(0, period - _ABBREVIATION_WINDOW) : period].split()
    if not tokens:
        return False
    word = tokens[-1].strip(_WORD_EDGE_MARKS).casefold()
    if len(word) == 1 and word.isalpha():
        previous = tokens[-2].casefold() if len(tokens) > 1 else ""
        return not (previous == _LIST_END_PREFIX and word in _LIST_END_LETTERS)
    return word in _ABBREVIATIONS


def has_cyrillic(text: str) -> bool:
    return _CYRILLIC_RE.search(text) is not None


def shorten(text: str, max_chars: int) -> str:
    """Cut text to at most max_chars at a word boundary and mark the cut with an ellipsis."""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - len(ELLIPSIS)]
    if not (cut[-1:].isspace() or text[len(cut)].isspace()):
        # The cut fell inside a word: drop that word unless it is the only one.
        parts = cut.rsplit(maxsplit=1)
        if len(parts) > 1:
            cut = parts[0]
    return cut.rstrip(_TRAILING_SEPARATORS) + ELLIPSIS
