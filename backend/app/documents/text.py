"""Word, sentence and stop-word helpers shared by chunking, statistics and offline analysis.

Every pattern here runs on untrusted document text, so each one must stay linear on hostile
input such as two million dots.
"""

# ruff: noqa: RUF001, RUF003 -- Cyrillic letters and typographic quotes are meant

import re
from collections.abc import Iterator
from typing import Final


def _word_set(text: str) -> frozenset[str]:
    return frozenset(text.split())


ELLIPSIS: Final = "…"
# Stands on a line of its own between the excerpts of a long document in an analysis sample.
EXCERPT_SEPARATOR: Final = f"\n[{ELLIPSIS}]\n"

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
# ("Dr. Watson", "Fig. 4", "рис. 2"). Ones that usually close a list ("etc.", "и др.",
# "т.д.") are left out, so a capital letter after them starts a new sentence.
_ABBREVIATIONS: Final = _word_set(
    """
    al approx apr aug ca capt cf ch chap col dec dr ed eds eq eqs feb fig figs gen jan jr jul
    jun lt mr mrs nov oct pp prof ref refs rev sep sept sgt sr st viz vol vols vs акад англ вв
    вып гг гл греч доц изд им кв лат напр обл пер пп просп проф разд ред рис ср ст стр табл
    тел тыс ул франц
    """
)
# Abbreviations only before a number: "no. 5", while "The answer is no." ends a sentence.
_NUMBER_ABBREVIATIONS: Final = frozenset({"no", "nos"})
# Abbreviations except after a number, where they are units: "Ms. Smith" and "см. рис. 2",
# while "50 ms." and "5 см." may end a sentence.
_UNIT_ABBREVIATIONS: Final = frozenset({"ms", "sec", "см"})
# Short groups of letters joined by dots ("U.S.", "Ph.D.", "e.g.", "т.е."); of these only
# "т.д." and "т.п." close a list and "a.m." and "p.m." a time, so those may end a sentence.
_DOTTED_ABBREVIATION_RE: Final = re.compile(r"[^\W\d_]{1,2}+(?:\.[^\W\d_]{1,2}+)++")
_DOTTED_SENTENCE_ENDS: Final = frozenset({"т.д", "т.п", "a.m", "p.m"})
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
STOPWORDS_FR: Final = _word_set(
    """
    à afin ai alors au aucun aucune aussi autre autres aux avaient avais avait avant avec avez
    avoir avons ayant bien ça car ce ceci cela celle celles celui ces cet cette ceux chacun
    chacune chaque chez comme comment dans de des dès donc dont du elle elles en encore entre
    est et étaient était étant été être eu eux fait font hors ici il ils je la là le les leur
    leurs lors lorsque lui ma mais me même mêmes mes moi moins mon ne ni nos notre nous on ont
    ou où par parce pas peu peut peuvent plus pour pourquoi puis puisque quand que quel quelle
    quelles quels qui quoi sa sans se selon ses si sinon soi soit son sont sous suis sur ta te
    tes toi ton tous tout toute toutes très tu un une vers vos votre vous y
    """
)
# Cardinal numbers written as words; "one", "один" and "un" are stop words already.
NUMBER_WORDS: Final = _word_set(
    """
    two three four five six seven eight nine ten hundred thousand million два две двух три
    трех четыре четырех пять шесть семь восемь девять десять сто тысяча миллион deux trois
    quatre cinq six sept huit neuf dix cent mille
    """
)


def words(text: str) -> list[str]:
    """The words of a text in reading order: runs of letters and digits of any script."""
    return _WORD_RE.findall(text)


def word_matches(text: str) -> Iterator[re.Match[str]]:
    """The words of a text in reading order, as words() finds them, with where they are."""
    return _WORD_RE.finditer(text)


def split_sentences(text: str) -> list[str]:
    """Split text into trimmed sentences; a closing quote or bracket stays with its sentence."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        single_period = match.group(1).rstrip(_CLOSING_MARKS) == "."
        if single_period and _is_abbreviation(text, match.start(), match.end()):
            continue
        if sentence := text[start : match.end(1)].strip():
            sentences.append(sentence)
        start = match.end()
    if tail := text[start:].strip():
        sentences.append(tail)
    return sentences


def _is_abbreviation(text: str, period: int, next_start: int) -> bool:
    """Whether the period at text[period] closes an initial or a known abbreviation.

    next_start is where the next sentence would begin if the period ended this one.
    """
    tokens = text[max(0, period - _ABBREVIATION_WINDOW) : period].split()
    if not tokens:
        return False
    word = tokens[-1].strip(_WORD_EDGE_MARKS).casefold()
    previous = tokens[-2].casefold() if len(tokens) > 1 else ""
    if len(word) == 1 and word.isalpha():
        return not (previous == _LIST_END_PREFIX and word in _LIST_END_LETTERS)
    if word in _NUMBER_ABBREVIATIONS:
        return text[next_start].isdigit()
    if word in _UNIT_ABBREVIATIONS:
        return not previous[-1:].isdigit()
    if _DOTTED_ABBREVIATION_RE.fullmatch(word):
        return word not in _DOTTED_SENTENCE_ENDS
    return word in _ABBREVIATIONS


def has_cyrillic(text: str) -> bool:
    return _CYRILLIC_RE.search(text) is not None


def shorten(text: str, max_chars: int) -> str:
    """Cut text to at most max_chars at a word boundary and mark the cut with an ellipsis."""
    if max_chars < len(ELLIPSIS):
        raise ValueError(f"max_chars must leave room for the ellipsis, got {max_chars}")
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - len(ELLIPSIS)]
    if not (cut[-1:].isspace() or text[len(cut)].isspace()):
        # The cut fell inside a word: drop that word unless it is the only one.
        parts = cut.rsplit(maxsplit=1)
        if len(parts) > 1:
            cut = parts[0]
    return cut.rstrip(_TRAILING_SEPARATORS) + ELLIPSIS
