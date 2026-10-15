"""The analysis a model returns and how it is tidied before it is stored."""

import unicodedata
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.documents.text import shorten
from app.models.document import SUMMARY_MAX_LENGTH, TITLE_MAX_LENGTH, Difficulty

MIN_TOPICS: Final = 1
MAX_TOPICS: Final = 8
TOPIC_MAX_LENGTH: Final = 60
# Control and format characters, and lone surrogates: UTF-8 cannot encode those, and text
# extracted from a PDF can contain them.
_DROPPED_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs"})


# What a model must return; it is also sent as the response schema. Strict structured
# output allows neither defaults nor string length limits, so normalize_analysis enforces
# lengths afterwards. No docstring: it would become the schema description sent to the
# model. No description on difficulty: strict schemas reject keywords beside a $ref.
class DocumentAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(description="A short title in the language of the document")
    summary: str = Field(description="Two or three sentences on what the material teaches")
    topics: list[str] = Field(
        min_length=MIN_TOPICS, max_length=MAX_TOPICS, description="Key topics, a few words each"
    )
    difficulty: Difficulty


@dataclass(frozen=True, slots=True)
class NormalizedAnalysis:
    """An analysis that fits the document columns; a blank title or summary is None."""

    title: str | None
    summary: str | None
    topics: list[str]
    difficulty: Difficulty


def normalize_analysis(analysis: DocumentAnalysis) -> NormalizedAnalysis:
    """Tidy an analysis from any provider so that it fits the columns it is stored in."""
    topics: list[str] = []
    seen: set[str] = set()
    for raw_topic in analysis.topics:
        topic = shorten(_tidy(raw_topic), TOPIC_MAX_LENGTH)
        if topic and topic.casefold() not in seen:
            seen.add(topic.casefold())
            topics.append(topic)
    return NormalizedAnalysis(
        title=shorten(_tidy(analysis.title), TITLE_MAX_LENGTH) or None,
        summary=shorten(_tidy(analysis.summary), SUMMARY_MAX_LENGTH) or None,
        topics=topics[:MAX_TOPICS],
        difficulty=analysis.difficulty,
    )


def _tidy(text: str) -> str:
    """Collapse whitespace, drop invisible and unencodable characters and compose to NFC."""
    tidy = " ".join(text.split())
    if not tidy.isprintable():
        kept = (char for char in tidy if unicodedata.category(char) not in _DROPPED_CATEGORIES)
        tidy = " ".join("".join(kept).split())
    return unicodedata.normalize("NFC", tidy)
