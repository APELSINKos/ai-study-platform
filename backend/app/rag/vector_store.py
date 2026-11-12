"""Search queries over the chunks of a workspace's ready documents.

A query gets two lists of candidates: the chunks whose embeddings are nearest to its own
(pgvector's cosine distance) and the chunks that match its words (PostgreSQL full-text
search). The chunks chosen from them are then read with their passages, and the documents
that a search covers are counted. The store only queries; the caller owns the transaction.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import CTE, ColumnElement, Select, case, cast, func, literal, select, text, true
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.orm import Session

from app.models.document import ACTIVE_DOCUMENT_STATUSES, Document
from app.models.document_chunk import DocumentChunk

# The configuration that the chunks' search_vector column is built with: words are only
# lower-cased, never stemmed, whatever the language.
TEXT_SEARCH_CONFIG: Final = "simple"
# A cost guard for any caller: longer text is cut before the word that the limit falls in.
MAX_KEYWORD_QUERY_CHARS: Final = 256
# websearch_to_tsquery reads a "-" that starts a word as NOT. A run of them, with only
# spaces or the signs !&|()< between, is as many NOTs waiting for one word, and the
# parser fails beyond 32 of those. Two NOTs cancel out, so a run becomes one or none.
_NOT_RUN_RE: Final = re.compile(r'(?<![^\s!&|()<"])-[-\s!&|()<]*+')
# querytree() is '' for a query without words, and 'T' for one that matches a chunk without
# any of its words, such as "-light" or "light or -eye": nearly every chunk would match it.
_UNSEARCHABLE_QUERY_TREES: Final = ("", "T")
# The HNSW index stops after hnsw.ef_search (40) candidates, before the workspace and
# status filters; an iterative scan goes on until enough rows pass them. strict_order can
# lose rows; relaxed_order may return a few out of order, so the query sorts them again.
ITERATIVE_SCAN_MODE: Final = "relaxed_order"
# SET LOCAL ends with the transaction; a plain SET would stay on the pooled connection.
_ITERATIVE_SCAN: Final = text(f"SET LOCAL hnsw.iterative_scan = {ITERATIVE_SCAN_MODE}")
# Cleaning removes control characters from every stored text, so a document cannot forge
# these marks.
HIGHLIGHT_START: Final = "\x01"
HIGHLIGHT_STOP: Final = "\x02"
FRAGMENT_DELIMITER: Final = "\x03"
# Up to two passages of 8 to 24 words around the words that the query matches.
HEADLINE_OPTIONS: Final = (
    f"StartSel={HIGHLIGHT_START}, StopSel={HIGHLIGHT_STOP}, MaxFragments=2, MaxWords=24,"
    f" MinWords=8, FragmentDelimiter={FRAGMENT_DELIMITER}"
)


@dataclass(frozen=True, slots=True)
class VectorCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    # Cosine distance from the query's embedding: 0 for the same direction, 1 for unrelated.
    distance: float


@dataclass(frozen=True, slots=True)
class KeywordCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    # ts_rank_cd: higher the more often, and the closer together, the query's words occur.
    rank: float


@dataclass(frozen=True, slots=True)
class ChunkHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    # The document's title, or its file name while it has none.
    document_title: str
    chunk_index: int
    heading: str | None
    page_start: int | None
    page_end: int | None
    content: str
    char_count: int
    # Passages of the content, joined by FRAGMENT_DELIMITER. The query's words in them stand
    # between HIGHLIGHT_START and HIGHLIGHT_STOP; excluded words are never marked. A chunk
    # that the query does not match shows its first words, unmarked.
    headline: str


@dataclass(frozen=True, slots=True)
class SearchScope:
    """The documents of a workspace, as a search covers them."""

    # Searched by their words and, unless stale, by their embeddings.
    ready_documents: int
    # Ready, but embedded by another model than the current one.
    stale_documents: int
    # Still waiting for, or going through, processing: not searched yet.
    pending_documents: int


def nearest_statement(
    workspace_id: uuid.UUID,
    vector: Sequence[float],
    *,
    embedding_model: str,
    limit: int,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> Select[uuid.UUID, uuid.UUID, float]:
    """The query of VectorStore.nearest, which runs it after turning on iterative scans."""
    # pgvector binds a list, not any sequence.
    distance = DocumentChunk.embedding.cosine_distance(list(vector)).label("distance")
    nearest = (
        select(DocumentChunk.id, DocumentChunk.document_id, distance)
        .join(Document, _same_document())
        .where(
            *_ready_chunks(workspace_id, document_ids),
            Document.embedding_model == embedding_model,
        )
        .order_by(distance)
        .limit(limit)
        .cte("nearest")
        .prefix_with("MATERIALIZED")
    )
    # PostgreSQL 17 knows that the CTE comes out ordered by distance and would trust that
    # order; "distance + 0" is an expression that it has to sort by.
    return select(nearest.c.id, nearest.c.document_id, nearest.c.distance).order_by(
        nearest.c.distance + 0, nearest.c.id
    )


def matching_statement(
    workspace_id: uuid.UUID,
    text: str,
    *,
    limit: int,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> Select[uuid.UUID, uuid.UUID, float]:
    """The query of VectorStore.matching."""
    query = _keyword_query(text)
    rank = func.ts_rank_cd(DocumentChunk.search_vector, query.c.q).label("rank")
    return (
        select(DocumentChunk.id, DocumentChunk.document_id, rank)
        .join(Document, _same_document())
        .join(query, true())
        .where(
            # It depends on the query alone, so PostgreSQL checks it once and, when it
            # fails, reads no chunk at all.
            _searchable(query),
            _matches(query),
            *_ready_chunks(workspace_id, document_ids),
        )
        .order_by(rank.desc(), DocumentChunk.id)
        .limit(limit)
    )


def hits_statement(
    workspace_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID], text: str
) -> Select[uuid.UUID, uuid.UUID, str, int, str | None, int | None, int | None, str, int, str]:
    """The query of VectorStore.hits."""
    query = _keyword_query(text)
    # ts_headline marks each word of the query it gets, even an excluded one, in any chunk.
    # So it gets the words only for a chunk that matching would find, and without the
    # excluded ones (querytree); other chunks, such as one found by its embedding alone,
    # show their first words unmarked.
    marked_words = case(
        (_searchable(query) & _matches(query), cast(func.querytree(query.c.q), TSQUERY)),
        else_=cast(literal(""), TSQUERY),
    )
    headline = func.ts_headline(
        TEXT_SEARCH_CONFIG, DocumentChunk.content, marked_words, HEADLINE_OPTIONS
    )
    return (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            func.coalesce(Document.title, Document.original_filename).label("document_title"),
            DocumentChunk.chunk_index,
            DocumentChunk.heading,
            DocumentChunk.page_start,
            DocumentChunk.page_end,
            DocumentChunk.content,
            DocumentChunk.char_count,
            headline.label("headline"),
        )
        .join(Document, _same_document())
        .join(query, true())
        .where(DocumentChunk.workspace_id == workspace_id, DocumentChunk.id.in_(chunk_ids))
    )


def scope_statement(
    workspace_id: uuid.UUID,
    *,
    embedding_model: str,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> Select[int, int, int]:
    """The query of VectorStore.scope."""
    is_ready = Document.status == "ready"
    statement = select(
        func.count().filter(is_ready).label("ready_documents"),
        func.count()
        .filter(is_ready, Document.embedding_model != embedding_model)
        .label("stale_documents"),
        func.count()
        .filter(Document.status.in_(ACTIVE_DOCUMENT_STATUSES))
        .label("pending_documents"),
    ).where(Document.workspace_id == workspace_id)
    if document_ids is not None:
        statement = statement.where(Document.id.in_(document_ids))
    return statement


def _same_document() -> ColumnElement[bool]:
    return (Document.id == DocumentChunk.document_id) & (
        Document.workspace_id == DocumentChunk.workspace_id
    )


def _ready_chunks(
    workspace_id: uuid.UUID, document_ids: Sequence[uuid.UUID] | None
) -> list[ColumnElement[bool]]:
    criteria = [DocumentChunk.workspace_id == workspace_id, Document.status == "ready"]
    if document_ids is not None:
        criteria.append(DocumentChunk.document_id.in_(document_ids))
    return criteria


def _keyword_query(text: str) -> CTE:
    """The words of the text as a tsquery, read like a web search, in a CTE q of one column q."""
    return select(
        func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, _keyword_text(text)).label("q")
    ).cte("q")


def _keyword_text(text: str) -> str:
    """The text as websearch_to_tsquery gets it: cut, each run of NOTs made one or none."""
    return _NOT_RUN_RE.sub(_one_not_or_none, _cut_to_limit(text))


def _cut_to_limit(text: str) -> str:
    """The text cut to MAX_KEYWORD_QUERY_CHARS before the word that the limit falls in."""
    if len(text) <= MAX_KEYWORD_QUERY_CHARS:
        return text
    cut = text[:MAX_KEYWORD_QUERY_CHARS]
    if not (cut[-1].isspace() or text[MAX_KEYWORD_QUERY_CHARS].isspace()):
        # A word longer than the limit is cut through rather than dropped.
        parts = cut.rsplit(maxsplit=1)
        if len(parts) > 1:
            cut = parts[0]
    return cut


def _one_not_or_none(run: re.Match[str]) -> str:
    return "-" if run.group().count("-") % 2 else " "


def _searchable(query: CTE) -> ColumnElement[bool]:
    return func.querytree(query.c.q).not_in(_UNSEARCHABLE_QUERY_TREES)


def _matches(query: CTE) -> ColumnElement[bool]:
    return DocumentChunk.search_vector.bool_op("@@")(query.c.q)


class VectorStore:
    """Search queries over document chunks. Holds no business rules and never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def nearest(
        self,
        workspace_id: uuid.UUID,
        vector: Sequence[float],
        *,
        embedding_model: str,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[VectorCandidate]:
        """The chunks nearest to the vector, nearest first and ties by id.

        Only chunks of ready documents embedded by embedding_model count: vectors of
        different models cannot be compared, even of the same size. Iterative index scans
        stay on for the rest of the transaction.
        """
        self._session.execute(_ITERATIVE_SCAN)
        statement = nearest_statement(
            workspace_id,
            vector,
            embedding_model=embedding_model,
            limit=limit,
            document_ids=document_ids,
        )
        return [
            VectorCandidate(chunk_id=row.id, document_id=row.document_id, distance=row.distance)
            for row in self._session.execute(statement)
        ]

    def matching(
        self,
        workspace_id: uuid.UUID,
        text: str,
        *,
        limit: int,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[KeywordCandidate]:
        """The chunks of ready documents that match the words of the text, best first.

        The text reads like a web search: quoted words form a phrase, "or" joins words of
        which one is enough, and a word after "-" must not occur. Text without words, or
        with excluded words only, matches nothing. Ties are broken by id.
        """
        statement = matching_statement(workspace_id, text, limit=limit, document_ids=document_ids)
        return [
            KeywordCandidate(chunk_id=row.id, document_id=row.document_id, rank=row.rank)
            for row in self._session.execute(statement)
        ]

    def hits(
        self, workspace_id: uuid.UUID, chunk_ids: Sequence[uuid.UUID], text: str
    ) -> list[ChunkHit]:
        """The workspace's chunks with these ids, in no particular order.

        Each comes with a headline that marks the words of the text which match it. An id
        of a chunk that is gone, or of another workspace, gets nothing.
        """
        return [
            ChunkHit(
                chunk_id=row.id,
                document_id=row.document_id,
                document_title=row.document_title,
                chunk_index=row.chunk_index,
                heading=row.heading,
                page_start=row.page_start,
                page_end=row.page_end,
                content=row.content,
                char_count=row.char_count,
                headline=row.headline,
            )
            for row in self._session.execute(hits_statement(workspace_id, chunk_ids, text))
        ]

    def scope(
        self,
        workspace_id: uuid.UUID,
        *,
        embedding_model: str,
        document_ids: Sequence[uuid.UUID] | None = None,
    ) -> SearchScope:
        """How many of the workspace's documents a search with this embedding model covers."""
        statement = scope_statement(
            workspace_id, embedding_model=embedding_model, document_ids=document_ids
        )
        row = self._session.execute(statement).one()
        return SearchScope(
            ready_documents=row.ready_documents,
            stale_documents=row.stale_documents,
            pending_documents=row.pending_documents,
        )
