import hashlib
import json
import time
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, Final

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.api.deps import get_query_embedder
from app.core.config import Settings
from app.core.logging import configure_logging
from app.documents.chunking import HEADING_SEPARATOR
from app.llm.base import (
    EMBEDDING_DIMENSIONS,
    ProviderError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from app.llm.mock_provider import MOCK_EMBEDDING_MODEL, HashingEmbeddingProvider
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.rag.vector_store import SearchScope, VectorStore
from app.repositories.document_chunks import ChunkRow, DocumentChunkRepository
from app.repositories.documents import DocumentRepository
from app.schemas.search import DEFAULT_LIMIT, MAX_LIMIT, QUERY_MAX_CHARS
from tests.api.conftest import csrf_headers

pytestmark = pytest.mark.integration

_SEARCH_PATH: Final = "/api/v1/search"
_WORKSPACES_PATH: Final = "/api/v1/workspaces"
_NOW: Final = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
# A model that embedded documents before the current one did.
_OTHER_MODEL: Final = "text-embedding-3-small"
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 1, "embedding_model": MOCK_EMBEDDING_MODEL, "processed_at": _NOW},
    "failed": {"error_code": "no_text"},
}
_LEAF: Final = "Photosynthesis turns light into sugar inside the chloroplasts of a leaf."
_REPEATED: Final = (
    "Photosynthesis needs light, photosynthesis makes sugar, and photosynthesis feeds the plant."
)
_PIGMENT: Final = (
    "Chlorophyll absorbs red and blue light and reflects the green part of the spectrum."
)
# Shares no word with "chloroplasts", only the beginning of one, which the built-in
# embeddings compare.
_STROMA: Final = "Each chloroplast holds stacks of thylakoid membranes."
_MITOCHONDRIA: Final = "Mitochondria release the energy stored in glucose."
_PLANT_CELLS: Final = "Plant cells capture light for photosynthesis in their chloroplasts."
_ANIMAL_CELLS: Final = "Animal cells divide by mitosis and have no chloroplasts at all."
# Made-up words, so that no other text of a test can contain them.
_PRIVATE_QUERY: Final = "quorvex zanthoplasm"
_PRIVATE_WORDS: Final = ("quorvex", "zanthoplasm")
_LONGEST_QUERY: Final = ("chlorophyll " * 17)[:QUERY_MAX_CHARS]
# Keys that every log line carries besides its own fields.
_LOG_KEYS: Final = {"event", "level", "logger", "timestamp", "request_id"}
_SEARCH_MODES: Final = ("hybrid", "vector", "keyword")
_EMBEDDING_OUTCOMES: Final = ("ok", "error")
_QUERY_EMBEDDING_OK: Final = {"operation": "query_embedding", "outcome": "ok"}


class _FakeQueryEmbedder:
    """Embeds queries as the built-in model does, or with a vector it is given.

    Records every call, with whether the database session had a transaction open at the
    time. Like the OpenAI embedder it refuses blank text with a plain ValueError, and it
    raises the error it is given, such as an unreachable or refusing provider's.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._builtin = HashingEmbeddingProvider()
        self.calls: list[list[str]] = []
        self.in_transaction: list[bool] = []
        self.vector: list[float] | None = None
        self.error: Exception | None = None

    @property
    def model_name(self) -> str:
        return MOCK_EMBEDDING_MODEL

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        self.in_transaction.append(self._session.in_transaction())
        if any(not text.strip() for text in texts):
            raise ValueError("Texts to embed must not be blank.")
        if self.error is not None:
            raise self.error
        if self.vector is not None:
            return [self.vector for _ in texts]
        return self._builtin.embed(texts)


@pytest.fixture(autouse=True)
def embedder(auth_app: FastAPI, db_session: Session) -> _FakeQueryEmbedder:
    """Embeds the queries of every search in this module."""
    fake = _FakeQueryEmbedder(db_session)
    auth_app.dependency_overrides[get_query_embedder] = lambda: fake
    return fake


def _create_workspace(client: TestClient, name: str = "Plant biology") -> str:
    response = client.post(_WORKSPACES_PATH, json={"name": name}, headers=csrf_headers(client))
    assert response.status_code == HTTPStatus.CREATED
    workspace_id: str = response.json()["id"]
    return workspace_id


def _add_document(
    session: Session, workspace_id: str, status: DocumentStatus = "ready", **values: object
) -> Document:
    """A document of the workspace, committed so that a request rolling back keeps it."""
    document_id = uuid.uuid4()
    fields: dict[str, object] = {
        "id": document_id,
        "workspace_id": uuid.UUID(workspace_id),
        "original_filename": "notes.md",
        "content_type": "text/markdown",
        "size_bytes": 1024,
        "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
        "storage_key": f"{workspace_id}/{document_id}.md",
        "status": status,
        **_STATUS_FIELDS.get(status, {}),
    }
    fields.update(values)
    document = DocumentRepository(session).add(Document(**fields))
    session.commit()
    return document


def _vector(*components: float) -> list[float]:
    """An embedding whose first components are these and the rest zero."""
    return [*components, *[0.0] * (EMBEDDING_DIMENSIONS - len(components))]


def _row(index: int, content: str, *, embedding: list[float] | None = None) -> ChunkRow:
    """A text-file chunk, embedded as the built-in model embeds it unless given an embedding."""
    [builtin] = HashingEmbeddingProvider().embed([content])
    return ChunkRow(
        chunk_index=index,
        content=content,
        heading=None,
        page_start=None,
        page_end=None,
        char_count=len(content),
        embedding=builtin if embedding is None else embedding,
    )


def _add_chunks(session: Session, document: Document, *rows: ChunkRow) -> list[str]:
    """Store the rows as the document's chunks; their ids as the API writes them, in order."""
    DocumentChunkRepository(session).replace_for_document(document.id, document.workspace_id, rows)
    statement = select(DocumentChunk.chunk_index, DocumentChunk.id).where(
        DocumentChunk.document_id == document.id
    )
    ids = {chunk_index: str(chunk_id) for chunk_index, chunk_id in session.execute(statement)}
    session.commit()
    return [ids[row.chunk_index] for row in rows]


def _search(client: TestClient, workspace_id: str, q: str, **params: str | int) -> httpx2.Response:
    return client.get(_SEARCH_PATH, params={"workspace_id": workspace_id, "q": q, **params})


def _results(client: TestClient, workspace_id: str, q: str, **params: str | int) -> dict[str, Any]:
    response = _search(client, workspace_id, q, **params)
    assert response.status_code == HTTPStatus.OK, response.text
    body: dict[str, Any] = response.json()
    return body


def _found(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The results of a search by chunk id."""
    return {hit["chunk_id"]: hit for hit in body["results"]}


def _highlighted(hit: dict[str, Any]) -> list[str]:
    return [part["text"] for part in hit["snippet"] if part["highlighted"]]


def _counts(body: dict[str, Any]) -> tuple[int, int, int]:
    return (
        body["searched_document_count"],
        body["stale_document_count"],
        body["pending_document_count"],
    )


def _assert_error(response: httpx2.Response, status: HTTPStatus, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def _events(output: str, event: str) -> list[dict[str, Any]]:
    lines = [json.loads(line) for line in output.splitlines() if line.strip()]
    return [line for line in lines if line["event"] == event]


def _timing_counts() -> dict[str, float]:
    """How many searches and query embeddings the API process has timed so far."""
    counts = {
        f"retrieval {mode}": REGISTRY.get_sample_value(
            "retrieval_duration_seconds_count", {"mode": mode}
        )
        for mode in _SEARCH_MODES
    } | {
        f"embedding {outcome}": REGISTRY.get_sample_value(
            "llm_request_duration_seconds_count",
            {"operation": "query_embedding", "outcome": outcome},
        )
        for outcome in _EMBEDDING_OUTCOMES
    }
    # A label set that has never been observed has no sample yet.
    return {name: count or 0.0 for name, count in counts.items()}


def _seconds_timed(histogram: str, labels: dict[str, str]) -> float:
    """The seconds that the API process has recorded in a histogram under these labels."""
    return REGISTRY.get_sample_value(f"{histogram}_sum", labels) or 0.0


# --- results --------------------------------------------------------------------


@pytest.mark.usefixtures("fresh_vector_index")
def test_a_result_is_a_passage_with_its_place_snippet_score_and_how_it_was_found(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    titled = _add_document(db_session, workspace_id, title="Plant biology")
    untitled = _add_document(
        db_session, workspace_id, original_filename="lecture-3.pdf", content_type="application/pdf"
    )
    embedder.vector = _vector(1.0)
    heading = f"Plants{HEADING_SEPARATOR}Leaves"
    both, words_only = _add_chunks(
        db_session,
        titled,
        replace(_row(0, _LEAF, embedding=_vector(1.0)), heading=heading),
        # Its embedding is unrelated to the query's: only its words match.
        _row(1, _REPEATED, embedding=_vector(0.0, 1.0)),
    )
    [similar_only] = _add_chunks(
        db_session,
        untitled,
        replace(_row(4, _PIGMENT, embedding=_vector(0.8, 0.6)), page_start=3, page_end=4),
    )

    body = _results(user_client, workspace_id, "photosynthesis")

    # Ranks: the vector list holds both (1) and similar_only (2), the keyword list
    # words_only (1, three matches) and both (2).
    assert body["results"] == [
        {
            "chunk_id": both,
            "document_id": str(titled.id),
            "document_title": "Plant biology",
            "chunk_index": 0,
            "heading": heading,
            "page_start": None,
            "page_end": None,
            "snippet": [
                {"text": "Photosynthesis", "highlighted": True},
                {
                    "text": " turns light into sugar inside the chloroplasts of a leaf",
                    "highlighted": False,
                },
            ],
            "score": pytest.approx(1 / 61 + 1 / 62),
            "matched_by": ["keyword", "semantic"],
            "similarity": pytest.approx(1.0),
        },
        {
            "chunk_id": words_only,
            "document_id": str(titled.id),
            "document_title": "Plant biology",
            "chunk_index": 1,
            "heading": None,
            "page_start": None,
            "page_end": None,
            "snippet": [
                {"text": "Photosynthesis", "highlighted": True},
                {"text": " needs light, ", "highlighted": False},
                {"text": "photosynthesis", "highlighted": True},
                {"text": " makes sugar, and ", "highlighted": False},
                {"text": "photosynthesis", "highlighted": True},
                {"text": " feeds the plant", "highlighted": False},
            ],
            "score": pytest.approx(1 / 61),
            "matched_by": ["keyword"],
            "similarity": None,
        },
        {
            "chunk_id": similar_only,
            "document_id": str(untitled.id),
            "document_title": "lecture-3.pdf",
            "chunk_index": 4,
            "heading": None,
            "page_start": 3,
            "page_end": 4,
            # No word of the query matches: the first words, nothing highlighted.
            "snippet": [
                {
                    "text": "Chlorophyll absorbs red and blue light and reflects",
                    "highlighted": False,
                }
            ],
            "score": pytest.approx(1 / 62),
            "matched_by": ["semantic"],
            "similarity": pytest.approx(0.8),
        },
    ]
    assert body["semantic_available"] is True
    assert _counts(body) == (2, 0, 0)
    assert embedder.calls == [["photosynthesis"]]


@pytest.mark.usefixtures("fresh_vector_index")
def test_the_built_in_embeddings_find_a_word_form_that_the_words_miss(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    stroma, leaf, _ = _add_chunks(
        db_session,
        _add_document(db_session, workspace_id),
        _row(0, _STROMA),
        _row(1, _LEAF),
        _row(2, _MITOCHONDRIA),
    )

    body = _results(user_client, workspace_id, "chloroplasts")

    assert [hit["chunk_id"] for hit in body["results"]] == [leaf, stroma]
    found = _found(body)
    assert found[leaf]["matched_by"] == ["keyword", "semantic"]
    assert _highlighted(found[leaf]) == ["chloroplasts"]
    assert found[stroma]["matched_by"] == ["semantic"]
    assert _highlighted(found[stroma]) == []
    assert body["semantic_available"] is True


@pytest.mark.usefixtures("fresh_vector_index")
def test_a_vector_search_finds_passages_by_their_embeddings_alone(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    stroma, leaf, _ = _add_chunks(
        db_session,
        _add_document(db_session, workspace_id),
        _row(0, _STROMA),
        _row(1, _LEAF),
        _row(2, _MITOCHONDRIA),
    )

    body = _results(user_client, workspace_id, "chloroplasts", mode="vector")

    assert [hit["chunk_id"] for hit in body["results"]] == [leaf, stroma]
    assert [hit["matched_by"] for hit in body["results"]] == [["semantic"], ["semantic"]]
    assert body["semantic_available"] is True
    assert embedder.calls == [["chloroplasts"]]


@pytest.mark.usefixtures("fresh_vector_index")
def test_the_least_similarity_that_a_search_keeps_comes_from_the_settings(
    user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    integration_settings: Settings,
) -> None:
    integration_settings.search_min_similarity = 0.9
    workspace_id = _create_workspace(user_client)
    embedder.vector = _vector(1.0)
    same, _ = _add_chunks(
        db_session,
        _add_document(db_session, workspace_id),
        _row(0, _LEAF, embedding=_vector(1.0)),
        _row(1, _PIGMENT, embedding=_vector(0.8, 0.6)),
    )

    body = _results(user_client, workspace_id, "chlorophyll", mode="vector")

    # Similarities of 1.0 and 0.8: the default of 0.05 would keep both.
    assert [(hit["chunk_id"], hit["similarity"]) for hit in body["results"]] == [
        (same, pytest.approx(1.0))
    ]


def test_a_keyword_search_never_embeds_the_query(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    leaf, _ = _add_chunks(
        db_session, _add_document(db_session, workspace_id), _row(0, _LEAF), _row(1, _STROMA)
    )

    body = _results(user_client, workspace_id, "chloroplasts", mode="keyword")

    assert [(hit["chunk_id"], hit["matched_by"], hit["similarity"]) for hit in body["results"]] == [
        (leaf, ["keyword"], None)
    ]
    assert body["semantic_available"] is False
    assert embedder.calls == []


@pytest.mark.usefixtures("fresh_vector_index")
def test_without_an_embeddings_key_searches_use_the_built_in_embeddings(
    user_client: TestClient, auth_app: FastAPI, db_session: Session
) -> None:
    del auth_app.dependency_overrides[get_query_embedder]
    workspace_id = _create_workspace(user_client)
    stroma, leaf = _add_chunks(
        db_session, _add_document(db_session, workspace_id), _row(0, _STROMA), _row(1, _LEAF)
    )

    body = _results(user_client, workspace_id, "chloroplasts")

    assert [hit["chunk_id"] for hit in body["results"]] == [leaf, stroma]
    assert body["semantic_available"] is True


def test_a_search_returns_at_most_limit_passages(
    user_client: TestClient, db_session: Session
) -> None:
    workspace_id = _create_workspace(user_client)
    rows = [
        _row(index, f"Photosynthesis note {index}: light becomes sugar.")
        for index in range(DEFAULT_LIMIT + 2)
    ]
    _add_chunks(db_session, _add_document(db_session, workspace_id), *rows)

    by_default = _results(user_client, workspace_id, "photosynthesis")
    three = _results(user_client, workspace_id, "photosynthesis", limit=3)
    most = _results(user_client, workspace_id, "photosynthesis", limit=MAX_LIMIT)

    assert len(by_default["results"]) == DEFAULT_LIMIT
    assert len(three["results"]) == 3
    assert len(most["results"]) == DEFAULT_LIMIT + 2


# --- what a search covers -------------------------------------------------------


@pytest.mark.usefixtures("fresh_vector_index")
def test_stale_and_pending_documents_are_counted_and_stale_ones_left_out_of_the_vector_list(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    current = _add_document(db_session, workspace_id)
    stale = _add_document(db_session, workspace_id, embedding_model=_OTHER_MODEL)
    processing = _add_document(db_session, workspace_id, "processing")
    for status in ("uploaded", "indexing", "failed"):
        _add_document(db_session, workspace_id, status)
    embedder.vector = _vector(1.0)
    [current_chunk] = _add_chunks(db_session, current, _row(0, _LEAF, embedding=_vector(1.0)))
    stale_words, _ = _add_chunks(
        db_session,
        stale,
        _row(0, _LEAF, embedding=_vector(1.0)),
        _row(1, _PIGMENT, embedding=_vector(1.0)),
    )
    # A document that is processed again keeps its old chunks until new ones replace them.
    _add_chunks(db_session, processing, _row(0, _LEAF, embedding=_vector(1.0)))

    body = _results(user_client, workspace_id, "photosynthesis")

    assert [hit["chunk_id"] for hit in body["results"]] == [current_chunk, stale_words]
    found = _found(body)
    assert found[current_chunk]["matched_by"] == ["keyword", "semantic"]
    # Its embedding equals the query's, but the vectors of two models cannot be compared.
    assert (found[stale_words]["matched_by"], found[stale_words]["similarity"]) == (
        ["keyword"],
        None,
    )
    assert _counts(body) == (2, 1, 3)
    assert body["semantic_available"] is True


def test_with_only_stale_documents_the_query_is_not_embedded(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    stale = _add_document(db_session, workspace_id, embedding_model=_OTHER_MODEL)
    [chunk] = _add_chunks(db_session, stale, _row(0, _LEAF))

    hybrid = _results(user_client, workspace_id, "photosynthesis")
    vector = _results(user_client, workspace_id, "photosynthesis", mode="vector")

    assert [(hit["chunk_id"], hit["matched_by"]) for hit in hybrid["results"]] == [
        (chunk, ["keyword"])
    ]
    assert vector["results"] == []
    for body in (hybrid, vector):
        assert body["semantic_available"] is False
        assert _counts(body) == (1, 1, 0)
    assert embedder.calls == []


def test_a_workspace_without_ready_documents_finds_nothing_and_embeds_nothing(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    processing = _add_document(db_session, workspace_id, "processing")
    _add_chunks(db_session, processing, _row(0, _LEAF))
    _add_document(db_session, workspace_id, "failed")
    empty_workspace_id = _create_workspace(user_client, "Chemistry")

    body = _results(user_client, workspace_id, "photosynthesis")
    empty = _results(user_client, empty_workspace_id, "photosynthesis")

    assert body == {
        "results": [],
        "semantic_available": False,
        "searched_document_count": 0,
        "stale_document_count": 0,
        "pending_document_count": 1,
    }
    assert (empty["results"], _counts(empty)) == ([], (0, 0, 0))
    assert embedder.calls == []


# --- the query ------------------------------------------------------------------


@pytest.mark.parametrize(
    "q", ["\x1f", "\x1c\N{ZERO WIDTH SPACE}\x07"], ids=["unit-separator", "invisible-mix"]
)
def test_a_query_of_control_characters_alone_finds_nothing_without_the_model(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder, q: str
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))

    body = _results(user_client, workspace_id, q)

    assert body == {
        "results": [],
        "semantic_available": False,
        "searched_document_count": 1,
        "stale_document_count": 0,
        "pending_document_count": 0,
    }
    # The OpenAI embedder would refuse the text as blank with an error of its own.
    assert embedder.calls == []


def test_the_query_is_cleaned_like_document_text_before_it_is_searched(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    [chunk] = _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))

    body = _results(
        user_client, workspace_id, "photo\N{SOFT HYPHEN}synthesis\n\N{ZERO WIDTH SPACE}light"
    )

    assert embedder.calls == [["photosynthesis light"]]
    [hit] = body["results"]
    assert hit["chunk_id"] == chunk
    assert _highlighted(hit) == ["Photosynthesis", "light"]


@pytest.mark.usefixtures("fresh_vector_index")
def test_a_query_of_excluded_words_alone_finds_nothing_in_any_mode(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(
        db_session,
        _add_document(db_session, workspace_id),
        _row(0, _LEAF),
        _row(1, _REPEATED),
        _row(2, _PIGMENT),
    )

    bodies = [
        _results(user_client, workspace_id, "-photosynthesis", mode=mode) for mode in _SEARCH_MODES
    ]

    for body in bodies:
        assert (body["results"], body["semantic_available"]) == ([], False)
    # Its embedding would find the very passages about photosynthesis.
    assert embedder.calls == []


@pytest.mark.usefixtures("fresh_vector_index")
def test_a_query_that_excludes_words_is_matched_by_its_words_alone(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _, animal_cells, _ = _add_chunks(
        db_session,
        _add_document(db_session, workspace_id),
        _row(0, _PLANT_CELLS),
        _row(1, _ANIMAL_CELLS),
        _row(2, _LEAF),
    )

    body = _results(user_client, workspace_id, "cells -photosynthesis")

    # No passage with "photosynthesis" comes back, however similar its embedding.
    assert [(hit["chunk_id"], hit["matched_by"]) for hit in body["results"]] == [
        (animal_cells, ["keyword"])
    ]
    assert body["semantic_available"] is False
    assert embedder.calls == []


def test_a_query_that_excludes_no_word_is_still_embedded(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _ANIMAL_CELLS))
    # A "-" inside a word, or two in a row that cancel out, exclude nothing.
    queries = ["cells", "photo-synthesis", "--cells"]

    bodies = [_results(user_client, workspace_id, q) for q in queries]

    assert [body["semantic_available"] for body in bodies] == [True, True, True]
    assert embedder.calls == [[q] for q in queries]


@pytest.mark.parametrize(
    ("q", "message"),
    [
        (" \t ", "String should have at least 1 character"),
        (f"{_LONGEST_QUERY}s", f"String should have at most {QUERY_MAX_CHARS} characters"),
        ("photo\x00synthesis", "Value error, must not contain the NUL character"),
    ],
    ids=["blank", "too-long", "nul"],
)
def test_the_query_is_stripped_held_to_its_length_and_refused_with_nul(
    user_client: TestClient, embedder: _FakeQueryEmbedder, q: str, message: str
) -> None:
    workspace_id = _create_workspace(user_client)

    response = _search(user_client, workspace_id, q)

    _assert_error(response, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert response.json()["error"]["details"] == [{"field": "q", "message": message}]
    assert embedder.calls == []


def test_the_query_length_is_measured_without_its_surrounding_spaces(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _PIGMENT))

    _results(user_client, workspace_id, f"  {_LONGEST_QUERY}\t ")

    assert embedder.calls == [[_LONGEST_QUERY]]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"q": "   "}, "q"),
        ({"q": f"{_LONGEST_QUERY}s"}, "q"),
        ({"q": "photo\x00synthesis"}, "q"),
        ({"q": "photosynthesis", "limit": 0}, "limit"),
        ({"q": "photosynthesis", "limit": MAX_LIMIT + 1}, "limit"),
        ({"q": "photosynthesis", "mode": "semantic"}, "mode"),
        ({"q": "photosynthesis", "workspace_id": "not-a-uuid"}, "workspace_id"),
        ({}, "q"),
    ],
    ids=[
        "blank",
        "too-long",
        "nul",
        "limit-0",
        "limit-too-high",
        "unknown-mode",
        "malformed-workspace-id",
        "missing-query",
    ],
)
def test_an_invalid_search_is_refused_before_anything_is_searched(
    user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    params: dict[str, str | int],
    field: str,
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))

    response = user_client.get(_SEARCH_PATH, params={"workspace_id": workspace_id, **params})

    _assert_error(response, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert [detail["field"] for detail in response.json()["error"]["details"]] == [field]
    assert "synthesis" not in response.text
    assert embedder.calls == []


# --- the query embedding --------------------------------------------------------


def test_no_database_transaction_is_open_while_the_query_is_embedded(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))

    for mode in ("hybrid", "vector"):
        _results(user_client, workspace_id, "photosynthesis", mode=mode)

    assert embedder.in_transaction == [False, False]


def test_the_signed_in_user_stays_loaded_while_the_query_is_embedded(
    user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))
    users_expired: list[list[bool]] = []
    embed = embedder.embed

    def embed_and_look_at_the_loaded_users(texts: Sequence[str]) -> list[list[float]]:
        loaded = db_session.identity_map.values()
        users_expired.append([inspect(user).expired for user in loaded if isinstance(user, User)])
        return embed(texts)

    monkeypatch.setattr(embedder, "embed", embed_and_look_at_the_loaded_users)

    _results(user_client, workspace_id, "photosynthesis")

    # One user, loaded and fresh. rollback() would expire it and close() would let it go;
    # either way, reading it again would open a transaction.
    assert users_expired == [[False]]


def test_no_database_transaction_is_left_open_after_a_search(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))

    for mode in _SEARCH_MODES:
        _results(user_client, workspace_id, "photosynthesis", mode=mode)

        assert not db_session.in_transaction(), mode


@pytest.mark.parametrize(
    "error",
    [
        ProviderUnavailableError("The AI provider could not be reached."),
        ProviderRequestError("The AI provider rejected the request: HTTP 400.", code="ai_rejected"),
    ],
    ids=["unavailable", "rejected"],
)
def test_when_the_query_cannot_be_embedded_a_hybrid_search_goes_on_with_its_words(
    user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    capsys: pytest.CaptureFixture[str],
    error: ProviderError,
) -> None:
    configure_logging("INFO", "json")
    workspace_id = _create_workspace(user_client)
    leaf, _ = _add_chunks(
        db_session, _add_document(db_session, workspace_id), _row(0, _LEAF), _row(1, _STROMA)
    )
    embedder.error = error

    body = _results(user_client, workspace_id, "chloroplasts")

    assert [(hit["chunk_id"], hit["matched_by"]) for hit in body["results"]] == [
        (leaf, ["keyword"])
    ]
    assert body["semantic_available"] is False
    assert len(embedder.calls) == 1
    [warning] = _events(capsys.readouterr().out, "search_embedding_failed")
    assert warning["level"] == "warning"
    assert warning["error_code"] == error.code
    assert set(warning) == {*_LOG_KEYS, "error_code"}


def test_a_vector_search_is_unavailable_while_the_provider_cannot_be_reached(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))
    embedder.error = ProviderUnavailableError("The AI provider did not answer in time.")

    response = _search(user_client, workspace_id, "photosynthesis", mode="vector")

    _assert_error(response, HTTPStatus.SERVICE_UNAVAILABLE, "search_unavailable")
    assert response.headers["retry-after"] == "30"


def test_a_vector_search_that_the_provider_refuses_is_unavailable_without_a_retry_time(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))
    embedder.error = ProviderRequestError(
        "The AI provider's quota or credit is used up: HTTP 402.", code="ai_quota_exceeded"
    )

    response = _search(user_client, workspace_id, "photosynthesis", mode="vector")

    _assert_error(response, HTTPStatus.SERVICE_UNAVAILABLE, "search_unavailable")
    assert "retry-after" not in response.headers


def test_an_embedder_that_fails_for_another_reason_is_an_internal_error(
    user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))
    # A bug, not a provider failure: no search should go on as if the model were down.
    embedder.error = RuntimeError("The embedder has a bug.")

    response = _search(user_client, workspace_id, _PRIVATE_QUERY)

    _assert_error(response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error")
    output = capsys.readouterr().out
    assert _events(output, "search_embedding_failed") == []
    assert len(_events(output, "unhandled_exception")) == 1
    for word in _PRIVATE_WORDS:
        assert word not in output.lower()


# --- access ---------------------------------------------------------------------


def test_another_users_workspace_is_not_found_and_nothing_is_embedded(
    user_client: TestClient,
    other_user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))

    responses = [
        _search(other_user_client, workspace_id, "photosynthesis"),
        _search(other_user_client, workspace_id, "photosynthesis", mode="keyword"),
        # Ownership is checked before the query is even cleaned.
        _search(other_user_client, workspace_id, "\x1f"),
        _search(user_client, str(uuid.uuid4()), "photosynthesis"),
    ]

    for response in responses:
        _assert_error(response, HTTPStatus.NOT_FOUND, "workspace_not_found")
        assert set(response.json()) == {"error"}
    assert embedder.calls == []
    assert _found(_results(user_client, workspace_id, "photosynthesis")) != {}


def test_another_users_workspace_is_refused_before_its_documents_are_counted(
    user_client: TestClient,
    other_user_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))
    counted: list[uuid.UUID] = []
    scope = VectorStore.scope

    def count_and_scope(
        store: VectorStore,
        workspace_id: uuid.UUID,
        *,
        embedding_model: str,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> SearchScope:
        counted.append(workspace_id)
        return scope(
            store, workspace_id, embedding_model=embedding_model, document_ids=document_ids
        )

    monkeypatch.setattr(VectorStore, "scope", count_and_scope)

    refused = _search(other_user_client, workspace_id, "photosynthesis")
    found = _search(user_client, workspace_id, "photosynthesis")

    _assert_error(refused, HTTPStatus.NOT_FOUND, "workspace_not_found")
    assert found.status_code == HTTPStatus.OK
    # Only the owner's search counted the documents of the workspace.
    assert counted == [uuid.UUID(workspace_id)]


def test_searching_needs_a_signed_in_user(
    auth_client: TestClient, embedder: _FakeQueryEmbedder
) -> None:
    response = _search(auth_client, str(uuid.uuid4()), "photosynthesis")

    _assert_error(response, HTTPStatus.UNAUTHORIZED, "not_authenticated")
    assert response.headers["www-authenticate"] == "Bearer"
    assert embedder.calls == []


def test_searches_past_the_limit_of_a_minute_are_rate_limited(
    user_client: TestClient,
    other_user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    integration_settings: Settings,
) -> None:
    integration_settings.searches_per_minute = 2
    workspace_id = _create_workspace(user_client)
    other_workspace_id = _create_workspace(other_user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))

    accepted = [_search(user_client, workspace_id, "photosynthesis") for _ in range(2)]
    limited = _search(user_client, workspace_id, "photosynthesis")
    other_user = _search(other_user_client, other_workspace_id, "photosynthesis")

    assert [response.status_code for response in accepted] == [HTTPStatus.OK] * 2
    _assert_error(limited, HTTPStatus.TOO_MANY_REQUESTS, "rate_limited")
    assert 0 < int(limited.headers["retry-after"]) <= 60
    assert other_user.status_code == HTTPStatus.OK
    # The limited search was refused before its query was embedded.
    assert len(embedder.calls) == 2


# --- logs and metrics -----------------------------------------------------------


def test_each_search_logs_one_line_with_its_sizes_and_times(
    user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    workspace_id = _create_workspace(user_client)
    _add_chunks(
        db_session, _add_document(db_session, workspace_id), _row(0, _LEAF), _row(1, _STROMA)
    )

    _results(user_client, workspace_id, "photosynthesis  light")
    _results(user_client, workspace_id, "chloroplasts", mode="keyword")

    hybrid, keyword = _events(capsys.readouterr().out, "search_completed")
    fields = {
        *_LOG_KEYS,
        "workspace_id",
        "mode",
        "query_chars",
        "result_count",
        "semantic_available",
        "embedding_ms",
        "retrieval_ms",
    }
    assert set(hybrid) == set(keyword) == fields
    assert (hybrid["level"], hybrid["workspace_id"], hybrid["mode"]) == (
        "info",
        workspace_id,
        "hybrid",
    )
    assert (hybrid["query_chars"], hybrid["result_count"], hybrid["semantic_available"]) == (
        len("photosynthesis light"),
        1,
        True,
    )
    assert hybrid["embedding_ms"] >= 0
    assert hybrid["retrieval_ms"] >= 0
    assert (keyword["mode"], keyword["query_chars"], keyword["result_count"]) == (
        "keyword",
        len("chloroplasts"),
        1,
    )
    assert (keyword["semantic_available"], keyword["embedding_ms"]) == (False, None)
    assert keyword["retrieval_ms"] >= 0


@pytest.mark.usefixtures("fresh_vector_index")
def test_the_query_text_never_reaches_the_logs_the_metrics_or_an_error(
    user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", "json")
    workspace_id = _create_workspace(user_client)
    _add_chunks(
        db_session,
        _add_document(db_session, workspace_id),
        _row(0, "Quorvex cells store zanthoplasm in their outer membrane."),
    )

    found = [
        _search(user_client, workspace_id, _PRIVATE_QUERY, mode=mode) for mode in _SEARCH_MODES
    ]
    embedder.error = ProviderUnavailableError("The AI provider could not be reached.")
    fallback = _search(user_client, workspace_id, _PRIVATE_QUERY)
    unavailable = _search(user_client, workspace_id, _PRIVATE_QUERY, mode="vector")
    too_long = _search(user_client, workspace_id, f"{_PRIVATE_QUERY} " * 11)
    with_nul = _search(user_client, workspace_id, f"{_PRIVATE_QUERY}\x00")
    metrics = user_client.get("/metrics").text

    assert [response.status_code for response in (*found, fallback)] == [HTTPStatus.OK] * 4
    assert all(response.json()["results"] for response in (*found, fallback))
    assert unavailable.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert too_long.status_code == with_nul.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    captured = capsys.readouterr()
    assert len(_events(captured.out, "search_completed")) == 4
    for text in (
        captured.out,
        captured.err,
        metrics,
        unavailable.text,
        too_long.text,
        with_nul.text,
    ):
        for word in _PRIVATE_WORDS:
            assert word not in text.lower()


def test_searches_are_timed_by_mode_and_query_embeddings_by_outcome(
    user_client: TestClient, db_session: Session, embedder: _FakeQueryEmbedder
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))
    before = _timing_counts()
    hybrid_sum = REGISTRY.get_sample_value("retrieval_duration_seconds_sum", {"mode": "hybrid"})

    _results(user_client, workspace_id, "photosynthesis")
    _results(user_client, workspace_id, "photosynthesis", mode="keyword")
    embedder.error = ProviderUnavailableError("The AI provider could not be reached.")
    _results(user_client, workspace_id, "photosynthesis")
    unavailable = _search(user_client, workspace_id, "photosynthesis", mode="vector")

    assert unavailable.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    after = _timing_counts()
    assert {name: after[name] - before[name] for name in after} == {
        "retrieval hybrid": 2,
        # The vector search stopped when its query could not be embedded.
        "retrieval vector": 0,
        "retrieval keyword": 1,
        "embedding ok": 1,
        "embedding error": 2,
    }
    new_sum = REGISTRY.get_sample_value("retrieval_duration_seconds_sum", {"mode": "hybrid"})
    assert new_sum is not None
    assert new_sum > (hybrid_sum or 0.0)


def test_the_retrieval_time_leaves_out_the_time_spent_embedding_the_query(
    user_client: TestClient,
    db_session: Session,
    embedder: _FakeQueryEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _create_workspace(user_client)
    _add_chunks(db_session, _add_document(db_session, workspace_id), _row(0, _LEAF))
    # A clock that stands still, except that embedding the query takes 5 seconds.
    now = 1000.0

    def clock() -> float:
        return now

    embed = embedder.embed

    def embed_in_five_seconds(texts: Sequence[str]) -> list[list[float]]:
        nonlocal now
        now += 5.0
        return embed(texts)

    monkeypatch.setattr(time, "perf_counter", clock)
    monkeypatch.setattr(embedder, "embed", embed_in_five_seconds)
    retrieval_before = _seconds_timed("retrieval_duration_seconds", {"mode": "hybrid"})
    embedding_before = _seconds_timed("llm_request_duration_seconds", _QUERY_EMBEDDING_OK)

    _results(user_client, workspace_id, "photosynthesis")

    retrieval = _seconds_timed("retrieval_duration_seconds", {"mode": "hybrid"})
    embedding = _seconds_timed("llm_request_duration_seconds", _QUERY_EMBEDDING_OK)
    assert retrieval - retrieval_before < 5.0
    assert embedding - embedding_before == pytest.approx(5.0)


# --- OpenAPI --------------------------------------------------------------------


def test_openapi_documents_the_search_route_its_limits_and_errors(
    auth_client: TestClient,
) -> None:
    schema = auth_client.get("/openapi.json").json()

    operation = schema["paths"][_SEARCH_PATH]["get"]
    assert set(operation["responses"]) == {"200", "401", "404", "422", "429", "503"}
    assert operation["tags"] == ["search"]
    assert operation["summary"]
    assert "security" in operation
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SearchResults"
    }
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert {name: parameter["required"] for name, parameter in parameters.items()} == {
        "workspace_id": True,
        "q": True,
        "limit": False,
        "mode": False,
    }
    assert all(parameter["in"] == "query" for parameter in parameters.values())
    assert all(parameter["description"] for parameter in parameters.values())
    assert parameters["workspace_id"]["schema"]["format"] == "uuid"
    query = parameters["q"]["schema"]
    assert (query["minLength"], query["maxLength"]) == (1, QUERY_MAX_CHARS)
    limit = parameters["limit"]["schema"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, MAX_LIMIT, DEFAULT_LIMIT)
    assert parameters["mode"]["schema"] == {
        "$ref": "#/components/schemas/SearchMode",
        "description": parameters["mode"]["description"],
        "default": "hybrid",
    }
    schemas = schema["components"]["schemas"]
    assert schemas["SearchMode"]["enum"] == ["hybrid", "vector", "keyword"]
    results = schemas["SearchResults"]
    assert results["properties"]["results"]["items"] == {"$ref": "#/components/schemas/SearchHit"}
    assert set(results["required"]) == set(results["properties"])
    hit = schemas["SearchHit"]
    assert hit["properties"]["snippet"]["items"] == {"$ref": "#/components/schemas/SnippetPart"}
    assert hit["properties"]["matched_by"]["items"] == {"$ref": "#/components/schemas/MatchKind"}
    assert set(hit["required"]) == set(hit["properties"])
    assert schemas["MatchKind"]["enum"] == ["keyword", "semantic"]
