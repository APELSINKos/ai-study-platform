"""How a search picks its passages from the candidates that the vector store finds.

A query is looked for in two ways: among the chunks whose embeddings are nearest to its own,
and among the chunks that contain its words. Reciprocal Rank Fusion merges the two ranked
lists into one, and the chunks at its top are read with their passages.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from app.rag.snippets import parse_headline
from app.rag.vector_store import ChunkHit, KeywordCandidate, VectorCandidate
from app.schemas.search import MatchKind, SearchMode, SnippetPart

# The k of Reciprocal Rank Fusion as Cormack, Clarke and Büttcher set it (SIGIR 2009).
RRF_K: Final = 60
# More than a search returns: a chunk that both lists rank low can outscore one that only a
# single list ranks first.
CANDIDATES_PER_LIST: Final = 40


class CandidateSource(Protocol):
    """The queries that a retriever needs; VectorStore answers them from the database."""

    def nearest(
        self,
        workspace_id: uuid.UUID,
        vector: Sequence[float],
        *,
        embedding_model: str,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[VectorCandidate]: ...

    def matching(
        self,
        workspace_id: uuid.UUID,
        text: str,
        *,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[KeywordCandidate]: ...

    def hits(
        self, workspace_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID], text: str
    ) -> list[ChunkHit]: ...


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk that a search found: its passage, its snippet and how it was found."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    chunk_index: int
    heading: str | None
    page_start: int | None
    page_end: int | None
    content: str
    char_count: int
    snippet: list[SnippetPart]
    # The Reciprocal Rank Fusion score; a search returns the highest first.
    score: float
    # "keyword" before "semantic" when both lists found the chunk.
    matched_by: tuple[MatchKind, ...]
    # 1 - cosine distance; None unless the vector list found the chunk.
    similarity: float | None
    # The ts_rank_cd weight from the keyword list, not a position in it; None unless that
    # list found the chunk.
    keyword_rank: float | None


def fuse_ranks(*ranked_lists: Sequence[uuid.UUID]) -> list[tuple[uuid.UUID, float]]:
    """Reciprocal Rank Fusion: each chunk id of the lists with its score, best first.

    Every list adds 1 / (RRF_K + rank) to the chunks it holds, ranks counted from 1. Equal
    scores go first to the chunk with the better rank in a single list, then to the lower id.
    """
    scores: dict[uuid.UUID, float] = {}
    best_ranks: dict[uuid.UUID, int] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
            best_ranks[chunk_id] = min(rank, best_ranks.get(chunk_id, rank))
    order = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], best_ranks[chunk_id], chunk_id))
    return [(chunk_id, scores[chunk_id]) for chunk_id in order]


class Retriever:
    """Finds the chunks of a workspace that best match a query."""

    def __init__(self, source: CandidateSource, *, min_similarity: float) -> None:
        self._source = source
        self._min_similarity = min_similarity

    def retrieve(  # noqa: PLR0913 -- the parts of one search; all but the query keyword-only
        self,
        workspace_id: uuid.UUID,
        text: str,
        vector: Sequence[float] | None,
        *,
        embedding_model: str,
        mode: SearchMode,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[RetrievedChunk]:
        """At most limit chunks that match the query, best first.

        vector is the query's embedding. hybrid reads the keyword list and, given a vector,
        the vector list; vector reads the vector list only, so nothing without a vector;
        keyword reads the keyword list only. Vector candidates less similar to the query
        than min_similarity are dropped before the lists are fused.
        """
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        semantic: list[VectorCandidate] = []
        if vector is not None and mode in ("hybrid", "vector"):
            nearest = self._source.nearest(
                workspace_id,
                vector,
                embedding_model=embedding_model,
                limit=CANDIDATES_PER_LIST,
                document_ids=document_ids,
            )
            semantic = [
                candidate for candidate in nearest if _similarity(candidate) >= self._min_similarity
            ]
        keyword: list[KeywordCandidate] = []
        if mode in ("hybrid", "keyword"):
            keyword = self._source.matching(
                workspace_id, text, limit=CANDIDATES_PER_LIST, document_ids=document_ids
            )
        fused = fuse_ranks(
            [candidate.chunk_id for candidate in semantic],
            [candidate.chunk_id for candidate in keyword],
        )[:limit]
        if not fused:
            return []
        similarities = {candidate.chunk_id: _similarity(candidate) for candidate in semantic}
        keyword_ranks = {candidate.chunk_id: candidate.rank for candidate in keyword}
        found = self._source.hits(workspace_id, [chunk_id for chunk_id, _ in fused], text)
        hits = {hit.chunk_id: hit for hit in found}
        return [
            _retrieved(
                hits[chunk_id], score, similarities.get(chunk_id), keyword_ranks.get(chunk_id)
            )
            for chunk_id, score in fused
            # A chunk deleted since the lists were read has no hit: it is left out, not replaced.
            if chunk_id in hits
        ]


def _similarity(candidate: VectorCandidate) -> float:
    return 1 - candidate.distance


def _retrieved(
    hit: ChunkHit, score: float, similarity: float | None, keyword_rank: float | None
) -> RetrievedChunk:
    matched_by: list[MatchKind] = []
    if keyword_rank is not None:
        matched_by.append("keyword")
    if similarity is not None:
        matched_by.append("semantic")
    return RetrievedChunk(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        document_title=hit.document_title,
        chunk_index=hit.chunk_index,
        heading=hit.heading,
        page_start=hit.page_start,
        page_end=hit.page_end,
        content=hit.content,
        char_count=hit.char_count,
        snippet=parse_headline(hit.headline),
        score=score,
        matched_by=tuple(matched_by),
        similarity=similarity,
        keyword_rank=keyword_rank,
    )
