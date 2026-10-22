# ruff: noqa: RUF001 -- Russian sample text is intended

import hashlib
import math
import struct
import time
from typing import Final

import pytest

from app.documents.text import ELLIPSIS, EXCERPT_SEPARATOR
from app.llm.base import (
    EMBEDDING_DIMENSIONS,
    AnalysisRequest,
    AnalysisResult,
    EmbeddingProvider,
    LLMProvider,
)
from app.llm.mock_provider import (
    MOCK_ANALYSIS_MODEL,
    MOCK_EMBEDDING_MODEL,
    SUMMARY_MAX_CHARS,
    TITLE_SENTENCE_MAX_CHARS,
    TOPIC_COUNT,
    HashingEmbeddingProvider,
    MockLLMProvider,
)
from app.llm.schemas import NormalizedAnalysis, normalize_analysis

HOSTILE_TEXT_LENGTH: Final = 2_000_000
HOSTILE_UNITS: Final = (".", "!?", "…", "#", " #", "-")
# Markup that the analysis reads past: badges, images, links, lines of HTML and tables,
# front matter fences and web addresses.
MARKUP_UNITS: Final = ("[![a](b)](", "![a](", "[a](", "<a", "|", "---\n", "https://", "www.")
# Timed with coverage's tracer paused (no_cover): tracing multiplies the time of every step.
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0
EMPHASIS_MARKS: Final = ("_", "*", "~")

EN_NOTES: Final = (
    "# Spaced repetition: how *Recall* schedules reviews\n"
    "\n"
    "Spaced repetition is a learning technique that schedules each review just before you\n"
    "are likely to forget the material. Every successful review increases the interval, so\n"
    "well-known flashcards appear rarely. A failed review resets the interval to ten minutes.\n"
    "\n"
    "## The SM-2 algorithm\n"
    "The SM-2 algorithm keeps an ease factor per flashcard and multiplies the interval by it.\n"
    "- Again: repeat in ten minutes.\n"
    "- Good: one day, then three days, then interval times ease.\n"
)
RU_LECTURE: Final = (
    "Лекция 3. Нормализация реляционных баз данных\n"
    "\n"
    "Нормализация — это процесс организации данных в базе данных, включающий создание таблиц\n"
    "и установление отношений между ними. Цель нормализации состоит в устранении\n"
    "избыточности и аномалий модификации данных.\n"
    "Первая нормальная форма требует атомарности значений атрибутов.\n"
    "Вторая нормальная форма дополнительно требует полной функциональной зависимости\n"
    "неключевых атрибутов от первичного ключа.\n"
    "Третья нормальная форма исключает транзитивные зависимости неключевых атрибутов.\n"
)
SIMPLE_TEXT: Final = (
    "The cat sat on the mat. It was a sunny day. The dog ran to the cat. "
    "They played all day long. Then they had a nap."
)

EN_TEXT: Final = (
    "Spaced repetition schedules each flashcard review just before you are likely to forget "
    "it. The interval grows after every successful review, so well-known cards appear rarely."
)
EN_QUERY: Final = "How does spaced repetition choose the next review interval for a flashcard?"
EN_UNRELATED: Final = (
    "Preheat the oven, whisk the eggs with sugar and bake the sponge cake for forty minutes."
)
RU_TEXT: Final = (
    "Интервальное повторение планирует повтор каждой карточки незадолго до того, как вы её "
    "забудете. После каждого успешного повтора интервал растёт."
)
RU_QUERY: Final = "Как интервальное повторение выбирает интервал для карточки?"
RU_INFLECTED_QUERY: Final = "Интервалы повторений карточек"
RU_UNRELATED: Final = "Разогрейте духовку, взбейте яйца с сахаром и выпекайте бисквит сорок минут."
# SHA-256 of the little-endian float32 vectors: any change to the hashing scheme shows here.
EN_TEXT_VECTOR_SHA256: Final = "4035a776e4ce3f2e94e4a34d2992e92a0f6fb92da0d12b0538c54253441e0af9"
RU_TEXT_VECTOR_SHA256: Final = "b229ea90b819483eae02b461d86b9deacf4997e76b258f7e3d64bb23d05f16d3"


@pytest.fixture
def embedder() -> HashingEmbeddingProvider:
    return HashingEmbeddingProvider()


@pytest.fixture
def llm() -> MockLLMProvider:
    return MockLLMProvider()


def _embed_one(embedder: HashingEmbeddingProvider, text: str) -> list[float]:
    [vector] = embedder.embed([text])
    return vector


def _cosine(first: list[float], second: list[float]) -> float:
    return math.fsum(a * b for a, b in zip(first, second, strict=True))


def _analyze(llm: MockLLMProvider, sample: str, filename: str = "notes.md") -> AnalysisResult:
    return llm.analyze_document(AnalysisRequest(filename=filename, outline="", sample=sample))


def test_the_offline_providers_follow_the_provider_protocols() -> None:
    llm: LLMProvider = MockLLMProvider()
    embedder: EmbeddingProvider = HashingEmbeddingProvider()

    assert llm.model_name == MOCK_ANALYSIS_MODEL == "mock-heuristic-v1"
    assert embedder.model_name == MOCK_EMBEDDING_MODEL == "mock-hashing-v1"


def test_each_text_gets_one_vector_of_the_column_dimensions(
    embedder: HashingEmbeddingProvider,
) -> None:
    vectors = embedder.embed([EN_TEXT, RU_TEXT, "", "   "])

    assert len(vectors) == 4
    assert all(len(vector) == EMBEDDING_DIMENSIONS for vector in vectors)


def test_no_texts_give_no_vectors(embedder: HashingEmbeddingProvider) -> None:
    assert embedder.embed([]) == []


@pytest.mark.parametrize(
    "text",
    [EN_TEXT, RU_TEXT, EN_NOTES, "word", "", "the and of", "2024 2025"],
    ids=["english", "russian", "markdown", "one-word", "empty", "stop-words", "digits"],
)
def test_every_vector_has_unit_length(embedder: HashingEmbeddingProvider, text: str) -> None:
    vector = _embed_one(embedder, text)

    assert math.isclose(math.fsum(value * value for value in vector), 1.0, abs_tol=1e-9)


def test_text_without_features_gets_one_fixed_unit_vector(
    embedder: HashingEmbeddingProvider,
) -> None:
    vectors = embedder.embed(["", "  \n\t ", "the and of", "и в на", "2024 42"])

    assert all(vector == vectors[0] for vector in vectors)
    assert max(vectors[0]) == 1.0
    assert vectors[0].count(0.0) == EMBEDDING_DIMENSIONS - 1


@pytest.mark.parametrize(
    ("text", "expected_sha256"),
    [(EN_TEXT, EN_TEXT_VECTOR_SHA256), (RU_TEXT, RU_TEXT_VECTOR_SHA256)],
    ids=["english", "russian"],
)
def test_vectors_match_the_recorded_ones(
    embedder: HashingEmbeddingProvider, text: str, expected_sha256: str
) -> None:
    vector = _embed_one(embedder, text)

    packed = struct.pack(f"<{EMBEDDING_DIMENSIONS}f", *vector)
    assert hashlib.sha256(packed).hexdigest() == expected_sha256


def test_a_vector_does_not_depend_on_the_rest_of_the_batch(
    embedder: HashingEmbeddingProvider,
) -> None:
    together = embedder.embed([EN_TEXT, RU_TEXT, EN_TEXT])

    english, russian = _embed_one(embedder, EN_TEXT), _embed_one(embedder, RU_TEXT)
    assert together == [english, russian, english]


@pytest.mark.parametrize(
    ("text", "same_as"),
    [
        ("Ёлка и ЁЛКА", "елка и елка"),
        ("ＳＱＬ ﬁle", "sql file"),
        ("rock’n’roll", "rock'n'roll"),
        ("The 2024 database of the year", "database year"),
        # Ё and й written as a base letter and a combining mark (NFD).
        ("Ёлка и йод, «йод»", "Ёлка и йод, «йод»"),
    ],
    ids=[
        "case-and-yo",
        "compatibility-forms",
        "apostrophes",
        "stop-words-and-numbers",
        "decomposed-letters",
    ],
)
def test_texts_that_differ_only_in_form_get_the_same_vector(
    embedder: HashingEmbeddingProvider, text: str, same_as: str
) -> None:
    assert _embed_one(embedder, text) == _embed_one(embedder, same_as)


def test_runs_too_long_to_be_words_are_ignored(embedder: HashingEmbeddingProvider) -> None:
    blob = "iVBORw0KGgoAAAANSUhEUgAA" * 10

    assert _embed_one(embedder, f"database {blob} year") == _embed_one(embedder, "database year")


@pytest.mark.parametrize(
    ("text", "query", "unrelated"),
    [(EN_TEXT, EN_QUERY, EN_UNRELATED), (RU_TEXT, RU_QUERY, RU_UNRELATED)],
    ids=["english", "russian"],
)
def test_a_query_sharing_words_is_closer_than_an_unrelated_text(
    embedder: HashingEmbeddingProvider, text: str, query: str, unrelated: str
) -> None:
    vector = _embed_one(embedder, text)

    related = _cosine(vector, _embed_one(embedder, query))
    other = _cosine(vector, _embed_one(embedder, unrelated))

    assert related > other + 0.2


def test_an_inflected_russian_query_still_matches(embedder: HashingEmbeddingProvider) -> None:
    similarity = _cosine(_embed_one(embedder, RU_TEXT), _embed_one(embedder, RU_INFLECTED_QUERY))

    assert similarity > 0.2


def test_english_notes_are_analysed_from_the_heading_and_the_first_sentences(
    llm: MockLLMProvider,
) -> None:
    analysis = _analyze(llm, EN_NOTES).analysis

    assert analysis.title == "Spaced repetition: how Recall schedules reviews"
    assert analysis.summary == (
        "Spaced repetition is a learning technique that schedules each review just before you "
        "are likely to forget the material. Every successful review increases the interval, so "
        "well-known flashcards appear rarely. A failed review resets the interval to ten minutes."
    )
    assert analysis.topics == ["review", "interval", "spaced", "repetition", "schedules"]
    assert analysis.difficulty == "medium"


def test_a_russian_lecture_is_titled_by_its_first_line(llm: MockLLMProvider) -> None:
    analysis = _analyze(llm, RU_LECTURE, filename="lecture_03_bd.txt").analysis

    assert analysis.title == "Лекция 3. Нормализация реляционных баз данных"
    assert analysis.summary == (
        "Нормализация — это процесс организации данных в базе данных, включающий создание таблиц "
        "и установление отношений между ними. Цель нормализации состоит в устранении "
        "избыточности и аномалий модификации данных. Первая нормальная форма требует "
        "атомарности значений атрибутов."
    )
    assert analysis.topics == ["нормальная", "данных", "форма", "атрибутов", "требует"]
    assert analysis.difficulty == "hard"


def test_simple_text_is_easy_and_titled_by_its_first_sentence(llm: MockLLMProvider) -> None:
    analysis = _analyze(llm, SIMPLE_TEXT, filename="kids.txt").analysis

    assert analysis.title == "The cat sat on the mat"
    assert analysis.summary == "The cat sat on the mat. The dog ran to the cat."
    assert analysis.topics == ["sunny", "played", "long"]
    assert analysis.difficulty == "easy"


@pytest.mark.parametrize(
    ("sample", "title"),
    [
        ("## Intro to C# ##\nBody text.", "Intro to C#"),
        ("### Sets and maps ###   \nBody text.", "Sets and maps"),
        ("#\n# 2024\n## Real title\nBody text.", "Real title"),
        ("#hashtag is not a heading\nBody text.", "#hashtag is not a heading"),
        ("####### Seven hashes\nBody text.", "####### Seven hashes"),
        ("Setup\n```bash\n# install the tools\n```\nRun the tests.", "Setup"),
        ("A [linked](https://example.com/x) `code` __title__\n\nBody.", "A linked code title"),
        ("Square x**2 in snake_case or a~~b\n\nBody.", "Square x**2 in snake_case or a~~b"),
    ],
    ids=[
        "closing-hashes-after-a-space",
        "closing-hashes-and-spaces",
        "headings-without-letters",
        "no-space-after-the-hash",
        "seven-hashes",
        "heading-inside-a-code-block",
        "inline-markup",
        "marks-inside-words",
    ],
)
def test_the_title_comes_from_the_first_markdown_heading_with_letters(
    llm: MockLLMProvider, sample: str, title: str
) -> None:
    assert _analyze(llm, sample).analysis.title == title


def test_a_long_first_sentence_is_cut_for_the_title(llm: MockLLMProvider) -> None:
    sample = (
        "This opening sentence is written to be much longer than eighty characters in total, "
        "so the title has to stop early. Second sentence."
    )

    title = _analyze(llm, sample).analysis.title

    assert title == (
        "This opening sentence is written to be much longer than eighty characters in" + ELLIPSIS
    )
    assert len(title) <= TITLE_SENTENCE_MAX_CHARS


def test_text_without_letters_is_titled_by_the_file_name(llm: MockLLMProvider) -> None:
    analysis = _analyze(llm, "12 34 56\n---\n7", filename="lecture_03-notes.v2.txt").analysis

    assert analysis.title == "Lecture 03 notes v2"
    assert analysis.topics == ["Lecture 03 notes v2"]
    assert analysis.summary == ""
    assert analysis.difficulty == "medium"


def test_code_blocks_stay_out_of_the_summary(llm: MockLLMProvider) -> None:
    sample = (
        "Install the command line tools before you start working on the exercises.\n"
        "```\n"
        "pip install the command line tools with every optional extra enabled\n"
        "```\n"
        "Then run the first exercise and compare your answer with the solution.\n"
    )

    summary = _analyze(llm, sample).analysis.summary

    assert summary == (
        "Install the command line tools before you start working on the exercises. "
        "Then run the first exercise and compare your answer with the solution."
    )


@pytest.mark.parametrize("marker", ["-", "*", "1.", "2)", "•", "▪"])
def test_list_items_become_finished_sentences_of_their_own(
    llm: MockLLMProvider, marker: str
) -> None:
    sample = (
        "Steps to follow\n"
        f"{marker} open the editor and create a new empty file for notes\n"
        f"  {marker} write down every new term together with a short example;\n"
    )

    summary = _analyze(llm, sample).analysis.summary

    assert summary == (
        "Open the editor and create a new empty file for notes. "
        "Write down every new term together with a short example;"
    )


def test_a_code_block_that_an_excerpt_cuts_off_ends_with_that_excerpt(
    llm: MockLLMProvider,
) -> None:
    sample = (
        "The first excerpt explains the setup in a few ordinary words.\n"
        "```python\n"
        "print('the excerpt ends inside this code block')"
        + EXCERPT_SEPARATOR
        + "The second excerpt goes on with another ordinary sentence here.\n"
    )

    summary = _analyze(llm, sample).analysis.summary

    assert summary == (
        "The first excerpt explains the setup in a few ordinary words. "
        "The second excerpt goes on with another ordinary sentence here."
    )


def test_a_line_without_letters_or_digits_separates_paragraphs(llm: MockLLMProvider) -> None:
    sample = (
        "The first excerpt ends with this rather ordinary sentence.\n"
        "[…]\n"
        "Another excerpt starts here with a second ordinary sentence.\n"
        "* * *\n"
        "A third excerpt closes the sample with one more sentence."
    )

    summary = _analyze(llm, sample).analysis.summary

    assert summary == (
        "The first excerpt ends with this rather ordinary sentence. "
        "Another excerpt starts here with a second ordinary sentence. "
        "A third excerpt closes the sample with one more sentence."
    )


def test_yaml_front_matter_gives_the_title_and_stays_out_of_the_rest(llm: MockLLMProvider) -> None:
    sample = (
        "---\n"
        'title: "Linear Algebra"\n'
        "date: 2024-09-01\n"
        "tags: [math, algebra, vectors]\n"
        "---\n"
        "\n"
        "A vector is an ordered list of numbers that describes a point in space.\n"
    )

    analysis = _analyze(llm, sample, filename="vectors.md").analysis

    assert analysis.title == "Linear Algebra"
    assert analysis.summary == (
        "A vector is an ordered list of numbers that describes a point in space."
    )
    assert not {"date", "tags", "algebra"} & set(" ".join(analysis.topics).split())


@pytest.mark.parametrize(
    ("sample", "title"),
    [
        (
            "---\ndate: 2024-09-01\n...\nA vector is an ordered list of numbers.\n",
            "A vector is an ordered list of numbers",
        ),
        (
            "---\n  title: Nested key\ntitle: '  '\n---\nA vector is an ordered list of numbers.",
            "A vector is an ordered list of numbers",
        ),
        ("---\nVectors and matrices\n", "Vectors and matrices"),
    ],
    ids=["no-title", "no-usable-title", "never-closed"],
)
def test_front_matter_without_a_title_leaves_the_title_to_the_text(
    llm: MockLLMProvider, sample: str, title: str
) -> None:
    assert _analyze(llm, sample).analysis.title == title


def test_html_blocks_and_badges_stay_out_of_the_title_summary_and_topics(
    llm: MockLLMProvider,
) -> None:
    sample = (
        '<p align="center">\n'
        '  <img src="docs/logo.png" alt="Logo" width="160">\n'
        "</p>\n"
        "\n"
        "[![Build](https://github.com/acme/graphs/actions/workflows/ci.yml/badge.svg)]"
        "(https://github.com/acme/graphs/actions)\n"
        "[![PyPI](https://img.shields.io/pypi/v/graphs.svg)](https://pypi.org/project/graphs/)\n"
        "\n"
        "![Diagram of a graph](docs/graph.png) Every graph keeps its nodes and edges in "
        "arrays. The guide at https://graphs.example.org/guide explains every graph method.\n"
    )

    analysis = _analyze(llm, sample, filename="README.md").analysis

    assert analysis.title == "Every graph keeps its nodes and edges in arrays"
    assert analysis.summary == (
        "Every graph keeps its nodes and edges in arrays. The guide at "
        "https://graphs.example.org/guide explains every graph method."
    )
    assert not {"https", "build", "pypi", "logo", "diagram"} & set(analysis.topics)


def test_table_rows_stay_out_of_the_summary(llm: MockLLMProvider) -> None:
    sample = (
        "| Тема | Часы |\n"
        "|------|------|\n"
        "| Процессы и потоки, планирование и синхронизация | 8 |\n"
        "\n"
        "Процесс — это программа во время выполнения вместе с её адресным пространством.\n"
    )

    summary = _analyze(llm, sample).analysis.summary

    assert summary == (
        "Процесс — это программа во время выполнения вместе с её адресным пространством."
    )


@pytest.mark.parametrize(
    "gap", ["\n", "\n\n"], ids=["straight-into-the-text", "before-a-blank-line"]
)
def test_a_title_line_names_the_document_and_stays_out_of_the_summary(
    llm: MockLLMProvider, gap: str
) -> None:
    # Text taken from a PDF has no blank line under its title.
    sample = (
        "Лекция 4. Нормализация реляционных баз данных"
        + gap
        + "Нормализация — это последовательное преобразование схемы базы данных. Цель "
        "такого преобразования — избавиться от повторов и противоречий в данных.\n"
    )

    analysis = _analyze(llm, sample, filename="lecture.pdf").analysis

    assert analysis.title == "Лекция 4. Нормализация реляционных баз данных"
    assert analysis.summary == (
        "Нормализация — это последовательное преобразование схемы базы данных. Цель такого "
        "преобразования — избавиться от повторов и противоречий в данных."
    )


def test_a_line_under_the_title_heading_that_stands_alone_stays_out_of_the_summary(
    llm: MockLLMProvider,
) -> None:
    sample = (
        "# Spaced repetition\n"
        "Lecture notes for the second week\n"
        "Every review moves the next one further into the future. Forgotten cards come "
        "back the next day.\n"
    )

    analysis = _analyze(llm, sample).analysis

    assert analysis.title == "Spaced repetition"
    assert analysis.summary == (
        "Every review moves the next one further into the future. Forgotten cards come back "
        "the next day."
    )


def test_a_first_line_that_the_next_one_goes_on_from_is_no_title(llm: MockLLMProvider) -> None:
    sample = (
        "A vector is an ordered list of numbers that describes a point in space. Two\n"
        "vectors of the same length can be added component by component.\n"
    )

    analysis = _analyze(llm, sample, filename="vectors.md").analysis

    assert (
        analysis.title == "A vector is an ordered list of numbers that describes a point in space"
    )
    assert analysis.summary == (
        "A vector is an ordered list of numbers that describes a point in space. Two vectors "
        "of the same length can be added component by component."
    )


def test_a_wrapped_line_starting_with_a_dash_continues_its_sentence(
    llm: MockLLMProvider,
) -> None:
    sample = "Нормализация\n— это процесс организации данных в базе данных.\nДалее."

    summary = _analyze(llm, sample).analysis.summary

    assert summary == "Нормализация — это процесс организации данных в базе данных."


def test_the_summary_is_capped(llm: MockLLMProvider) -> None:
    sentence = "Every review moves the next interval further into the future " * 4
    sample = " ".join(f"{sentence.strip()} number {index}." for index in range(5))

    summary = _analyze(llm, sample).analysis.summary

    assert len(summary) <= SUMMARY_MAX_CHARS
    assert summary.endswith(ELLIPSIS)


def test_headings_of_the_outline_count_towards_the_topics(llm: MockLLMProvider) -> None:
    request = AnalysisRequest(
        filename="db.md",
        outline="Транзакции\nУровни изоляции транзакций",
        sample="Короткая заметка о базах данных.",
    )

    topics = llm.analyze_document(request).analysis.topics

    assert topics[0] == "транзакции"
    assert len(topics) == TOPIC_COUNT


def test_the_analysis_is_deterministic_and_free(llm: MockLLMProvider) -> None:
    first = _analyze(llm, RU_LECTURE)
    second = _analyze(MockLLMProvider(), RU_LECTURE)

    assert first == second
    assert first.model == MOCK_ANALYSIS_MODEL
    assert (first.prompt_tokens, first.completion_tokens) == (0, 0)


@pytest.mark.parametrize(
    ("sample", "filename"),
    [
        (EN_NOTES, "notes.md"),
        (RU_LECTURE, "notes.md"),
        (SIMPLE_TEXT, "notes.md"),
        ("# " + "word " * 500, "notes.md"),
        ("12 34", "_" * 251 + ".txt"),
    ],
    ids=["english-notes", "russian-lecture", "simple-text", "long-heading", "long-file-name"],
)
def test_normalizing_the_offline_analysis_changes_nothing(
    llm: MockLLMProvider, sample: str, filename: str
) -> None:
    analysis = _analyze(llm, sample, filename=filename).analysis

    assert normalize_analysis(analysis) == NormalizedAnalysis(
        title=analysis.title,
        summary=analysis.summary or None,
        topics=analysis.topics,
        difficulty=analysis.difficulty,
    )


@pytest.mark.no_cover
@pytest.mark.parametrize("unit", HOSTILE_UNITS)
def test_long_runs_of_punctuation_and_markup_are_processed_in_linear_time(
    llm: MockLLMProvider, embedder: HashingEmbeddingProvider, unit: str
) -> None:
    text = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    analysis = _analyze(llm, text, filename="hostile.txt").analysis
    embedder.embed([text])

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
    assert analysis.title == "Hostile"


@pytest.mark.no_cover
@pytest.mark.parametrize("unit", MARKUP_UNITS)
def test_long_runs_of_markup_are_analysed_in_linear_time(llm: MockLLMProvider, unit: str) -> None:
    text = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    _analyze(llm, text, filename="hostile.md")

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS


@pytest.mark.no_cover
@pytest.mark.parametrize("mark", EMPHASIS_MARKS)
def test_a_long_run_of_emphasis_marks_inside_a_word_is_processed_in_linear_time(
    llm: MockLLMProvider, embedder: HashingEmbeddingProvider, mark: str
) -> None:
    # A run between two letters, like the blank in "Name________Date", is not emphasis.
    text = "a" + mark * (HOSTILE_TEXT_LENGTH - 2) + "b"

    started = time.perf_counter()
    _analyze(llm, text, filename="hostile.txt")
    embedder.embed([text])

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS
