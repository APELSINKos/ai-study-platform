import uuid
from collections.abc import Collection, Sequence
from typing import Final

import pytest

from app.rag.retriever import CandidateSource, RetrievedChunk, Retriever, fuse_ranks
from app.rag.vector_store import (
    HIGHLIGHT_START,
    HIGHLIGHT_STOP,
    ChunkHit,
    KeywordCandidate,
    VectorCandidate,
    VectorStore,
)
from app.schemas.search import SearchMode, SnippetPart

_WORKSPACE_ID: Final = uuid.UUID("3b9d6f2a-71c4-4e58-a0d3-5c8e1f7b2a64")
_DOCUMENT_ID: Final = uuid.UUID("8e2a4c71-0f5d-4b96-b3e8-6d1a9c4f7e20")
_QUERY: Final = "light reaction"
# The fake source never reads the vector, it only records it.
_VECTOR: Final = (0.6, 0.8)
_MODEL: Final = "mock-hashing-v1"
_LIMIT: Final = 10


def _id(number: int) -> uuid.UUID:
    """A chunk id that sorts as its number does."""
    return uuid.UUID(int=number)


_SEMANTIC: Final = _id(1)
_KEYWORD: Final = _id(2)


def _hit(chunk_id: uuid.UUID) -> ChunkHit:
    """The chunk as the store would read it, every field made from the id's number."""
    number = chunk_id.int
    content = f"Passage {number} on the light reaction."
    return ChunkHit(
        chunk_id=chunk_id,
        document_id=_DOCUMENT_ID,
        document_title="Photosynthesis",
        chunk_index=number,
        heading=f"Chapter {number}",
        page_start=number,
        page_end=number + 1,
        content=content,
        char_count=len(content),
        headline=f"Passage {number} on the {HIGHLIGHT_START}light{HIGHLIGHT_STOP} reaction.",
    )


class _FakeSource:
    """Fixed candidate lists; records every call made to it.

    hits() answers for the chunks asked for, except the deleted ones, in the reverse order
    unless told otherwise: the store promises no order.
    """

    def __init__(
        self,
        *,
        nearest: Sequence[VectorCandidate] = (),
        matching: Sequence[KeywordCandidate] = (),
        deleted: Collection[uuid.UUID] = (),
        reverse_hits: bool = True,
    ) -> None:
        self._nearest = list(nearest)
        self._matching = list(matching)
        self._deleted = set(deleted)
        self._reverse_hits = reverse_hits
        self.nearest_calls: list[dict[str, object]] = []
        self.matching_calls: list[dict[str, object]] = []
        self.hits_calls: list[dict[str, object]] = []

    def nearest(
        self,
        workspace_id: uuid.UUID,
        vector: Sequence[float],
        *,
        embedding_model: str,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[VectorCandidate]:
        self.nearest_calls.append(
            {
                "workspace_id": workspace_id,
                "vector": vector,
                "embedding_model": embedding_model,
                "limit": limit,
                "document_ids": document_ids,
            }
        )
        return self._nearest

    def matching(
        self,
        workspace_id: uuid.UUID,
        text: str,
        *,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[KeywordCandidate]:
        self.matching_calls.append(
            {
                "workspace_id": workspace_id,
                "text": text,
                "limit": limit,
                "document_ids": document_ids,
            }
        )
        return self._matching

    def hits(
        self, workspace_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID], text: str
    ) -> list[ChunkHit]:
        self.hits_calls.append(
            {"workspace_id": workspace_id, "chunk_ids": list(chunk_ids), "text": text}
        )
        found = [_hit(chunk_id) for chunk_id in chunk_ids if chunk_id not in self._deleted]
        return found[::-1] if self._reverse_hits else found


def _store_is_a_source(store: VectorStore) -> CandidateSource:
    # mypy checks that VectorStore fits the protocol; names of positional parameters are not
    # compared.
    return store


def _near(chunk_id: uuid.UUID, distance: float) -> VectorCandidate:
    return VectorCandidate(chunk_id=chunk_id, document_id=_DOCUMENT_ID, distance=distance)


def _match(chunk_id: uuid.UUID, rank: float) -> KeywordCandidate:
    return KeywordCandidate(chunk_id=chunk_id, document_id=_DOCUMENT_ID, rank=rank)


def _retrieve(
    source: _FakeSource,
    *,
    mode: SearchMode = "hybrid",
    vector: Sequence[float] | None = _VECTOR,
    limit: int = _LIMIT,
    min_similarity: float = 0.0,
) -> list[RetrievedChunk]:
    retriever = Retriever(source, min_similarity=min_similarity)
    return retriever.retrieve(
        _WORKSPACE_ID, _QUERY, vector, embedding_model=_MODEL, mode=mode, limit=limit
    )


def _ids(chunks: Sequence[RetrievedChunk]) -> list[uuid.UUID]:
    return [chunk.chunk_id for chunk in chunks]


def test_fusion_adds_one_over_sixty_plus_the_rank_from_every_list_that_holds_a_chunk() -> None:
    a, b, c = _id(1), _id(2), _id(3)

    assert fuse_ranks([a, b, c], [c, a]) == [
        (a, 1 / 61 + 1 / 62),
        (c, 1 / 63 + 1 / 61),
        (b, 1 / 62),
    ]


def test_a_chunk_in_one_list_scores_by_its_rank_there_alone() -> None:
    a, b = _id(1), _id(2)

    assert fuse_ranks([a, b], []) == [(a, 1 / 61), (b, 1 / 62)]
    assert fuse_ranks([], [b, a]) == [(b, 1 / 61), (a, 1 / 62)]


def test_empty_lists_fuse_into_nothing() -> None:
    assert fuse_ranks() == []
    assert fuse_ranks([], []) == []


def test_equal_scores_go_to_the_lower_chunk_id() -> None:
    low, high = _id(1), _id(2)

    # First in one list each: the same score and the same best rank.
    assert fuse_ranks([high], [low]) == [(low, 1 / 61), (high, 1 / 61)]
    assert fuse_ranks([low], [high]) == [(low, 1 / 61), (high, 1 / 61)]


def test_equal_scores_go_first_to_the_chunk_with_the_better_rank_in_a_single_list() -> None:
    # 1/63 + 1/84 = 1/72 + 1/72, in floats too: third and 24th score what twelfth in both
    # lists does.
    third_and_24th, twelfth_twice = _id(2), _id(1)
    vector = [
        *(_id(100 + number) for number in range(2)),
        third_and_24th,
        *(_id(200 + number) for number in range(8)),
        twelfth_twice,
    ]
    keyword = [
        *(_id(300 + number) for number in range(11)),
        twelfth_twice,
        *(_id(400 + number) for number in range(11)),
        third_and_24th,
    ]

    fused = fuse_ranks(vector, keyword)

    scores = dict(fused)
    assert scores[third_and_24th] == scores[twelfth_twice]
    order = [chunk_id for chunk_id, _ in fused]
    # The lower id would have put the chunk ranked twelfth twice first.
    assert order.index(third_and_24th) < order.index(twelfth_twice)


def test_hybrid_mode_fuses_both_lists_and_tells_what_found_each_chunk() -> None:
    semantic_only, both, keyword_only = _id(1), _id(2), _id(3)
    source = _FakeSource(
        nearest=[_near(semantic_only, 0.25), _near(both, 0.5)],
        matching=[_match(both, 0.75), _match(keyword_only, 0.5)],
    )

    chunks = _retrieve(source)

    assert [
        (chunk.chunk_id, chunk.score, chunk.matched_by, chunk.similarity, chunk.keyword_rank)
        for chunk in chunks
    ] == [
        (both, 1 / 62 + 1 / 61, ("keyword", "semantic"), 0.5, 0.75),
        (semantic_only, 1 / 61, ("semantic",), 0.75, None),
        (keyword_only, 1 / 62, ("keyword",), None, 0.5),
    ]


@pytest.mark.parametrize(
    ("mode", "vector", "expected", "calls"),
    [
        ("hybrid", _VECTOR, [_SEMANTIC, _KEYWORD], (1, 1, 1)),
        ("hybrid", None, [_KEYWORD], (0, 1, 1)),
        ("vector", _VECTOR, [_SEMANTIC], (1, 0, 1)),
        ("vector", None, [], (0, 0, 0)),
        ("keyword", _VECTOR, [_KEYWORD], (0, 1, 1)),
        ("keyword", None, [_KEYWORD], (0, 1, 1)),
    ],
    ids=[
        "hybrid",
        "hybrid-without-vector",
        "vector",
        "vector-without-vector",
        "keyword",
        "keyword-without-vector",
    ],
)
def test_each_mode_reads_only_the_lists_it_uses(
    mode: SearchMode,
    vector: Sequence[float] | None,
    expected: list[uuid.UUID],
    calls: tuple[int, int, int],
) -> None:
    source = _FakeSource(nearest=[_near(_SEMANTIC, 0.5)], matching=[_match(_KEYWORD, 0.5)])

    chunks = _retrieve(source, mode=mode, vector=vector)

    assert _ids(chunks) == expected
    # Calls to nearest, matching and hits.
    assert (len(source.nearest_calls), len(source.matching_calls), len(source.hits_calls)) == calls


def test_vector_candidates_below_the_minimum_similarity_are_dropped_and_equal_ones_kept() -> None:
    close, at_minimum, far = _id(1), _id(2), _id(3)
    source = _FakeSource(nearest=[_near(close, 0.5), _near(at_minimum, 0.75), _near(far, 0.875)])

    chunks = _retrieve(source, mode="vector", min_similarity=0.25)

    assert [(chunk.chunk_id, chunk.similarity) for chunk in chunks] == [
        (close, 0.5),
        (at_minimum, 0.25),
    ]
    assert source.hits_calls[0]["chunk_ids"] == [close, at_minimum]


def test_a_dropped_vector_candidate_can_still_come_from_the_keyword_list() -> None:
    chunk = _id(1)
    source = _FakeSource(nearest=[_near(chunk, 0.875)], matching=[_match(chunk, 0.5)])

    (found,) = _retrieve(source, min_similarity=0.25)

    assert (found.score, found.matched_by, found.similarity, found.keyword_rank) == (
        1 / 61,
        ("keyword",),
        None,
        0.5,
    )


@pytest.mark.parametrize(
    "nearest",
    [[], [_near(_SEMANTIC, 0.875)]],
    ids=["empty-lists", "only-dissimilar-candidates"],
)
def test_a_search_that_finds_nothing_reads_no_hits(nearest: list[VectorCandidate]) -> None:
    source = _FakeSource(nearest=nearest)

    assert _retrieve(source, min_similarity=0.25) == []
    assert source.hits_calls == []


def test_only_the_first_limit_fused_chunks_are_read_and_returned() -> None:
    ids = [_id(number) for number in range(1, 6)]
    source = _FakeSource(matching=[_match(chunk_id, 0.5) for chunk_id in ids])

    chunks = _retrieve(source, limit=3)

    assert _ids(chunks) == ids[:3]
    assert source.hits_calls == [
        {"workspace_id": _WORKSPACE_ID, "chunk_ids": ids[:3], "text": _QUERY}
    ]


def test_a_chunk_deleted_since_the_lists_were_read_is_left_out_not_replaced() -> None:
    deleted, kept, next_best = _id(1), _id(2), _id(3)
    source = _FakeSource(
        matching=[_match(deleted, 0.75), _match(kept, 0.5), _match(next_best, 0.25)],
        deleted=[deleted],
    )

    chunks = _retrieve(source, limit=2)

    assert _ids(chunks) == [kept]
    assert [call["chunk_ids"] for call in source.hits_calls] == [[deleted, kept]]


@pytest.mark.parametrize("reverse_hits", [False, True], ids=["as-asked", "reversed"])
def test_chunks_come_in_fused_order_whatever_order_the_hits_come_in(reverse_hits: bool) -> None:
    first, second, third = _id(3), _id(1), _id(2)
    source = _FakeSource(
        matching=[_match(first, 0.75), _match(second, 0.5), _match(third, 0.25)],
        reverse_hits=reverse_hits,
    )

    assert _ids(_retrieve(source)) == [first, second, third]


def test_a_retrieved_chunk_carries_its_hit_and_a_snippet_made_from_the_headline() -> None:
    chunk = _id(7)
    source = _FakeSource(matching=[_match(chunk, 0.5)])

    assert _retrieve(source, mode="keyword") == [
        RetrievedChunk(
            chunk_id=chunk,
            document_id=_DOCUMENT_ID,
            document_title="Photosynthesis",
            chunk_index=7,
            heading="Chapter 7",
            page_start=7,
            page_end=8,
            content="Passage 7 on the light reaction.",
            char_count=32,
            snippet=[
                SnippetPart(text="Passage 7 on the ", highlighted=False),
                SnippetPart(text="light", highlighted=True),
                SnippetPart(text=" reaction.", highlighted=False),
            ],
            score=1 / 61,
            matched_by=("keyword",),
            similarity=None,
            keyword_rank=0.5,
        )
    ]


def test_the_lists_are_asked_for_forty_candidates_of_the_model_and_documents_given() -> None:
    chunk = _id(1)
    documents = [_id(500), _id(501)]
    source = _FakeSource(nearest=[_near(chunk, 0.5)], matching=[_match(chunk, 0.5)])
    retriever = Retriever(source, min_similarity=0.0)

    retriever.retrieve(
        _WORKSPACE_ID, _QUERY, _VECTOR, embedding_model=_MODEL, mode="hybrid", limit=5
    )
    retriever.retrieve(
        _WORKSPACE_ID,
        _QUERY,
        _VECTOR,
        embedding_model=_MODEL,
        mode="hybrid",
        limit=5,
        document_ids=documents,
    )

    assert source.nearest_calls == [
        {
            "workspace_id": _WORKSPACE_ID,
            "vector": _VECTOR,
            "embedding_model": _MODEL,
            "limit": 40,
            "document_ids": filtered,
        }
        for filtered in (None, documents)
    ]
    assert source.matching_calls == [
        {"workspace_id": _WORKSPACE_ID, "text": _QUERY, "limit": 40, "document_ids": filtered}
        for filtered in (None, documents)
    ]
    hits_call = {"workspace_id": _WORKSPACE_ID, "chunk_ids": [chunk], "text": _QUERY}
    assert source.hits_calls == [hits_call, hits_call]


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_is_rejected(limit: int) -> None:
    source = _FakeSource(matching=[_match(_KEYWORD, 0.5)])

    with pytest.raises(ValueError, match="limit"):
        _retrieve(source, limit=limit)
    assert source.matching_calls == []
