"""Search over the passages of a user's workspace.

A search reads what the workspace holds in one short transaction, embeds the query with no
transaction open, since the model may take seconds to answer, and finds the passages in a
second transaction. The query's text is never logged, stored or put into an error.
"""

import time
import uuid
from collections.abc import Sequence
from typing import Final, Literal

import structlog
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.metrics import LLM_REQUEST_DURATION, RETRIEVAL_DURATION
from app.core.timing import to_ms
from app.documents.cleaning import clean_text
from app.llm.base import EmbeddingProvider, ProviderError
from app.models.user import User
from app.rag.retriever import RetrievedChunk, Retriever
from app.rag.vector_store import SearchScope, VectorStore
from app.repositories.workspaces import WorkspaceRepository
from app.schemas.search import SearchHit, SearchMode, SearchResults
from app.services.workspaces import workspace_not_found

logger = structlog.get_logger(__name__)

# How long to wait before a vector search is worth trying again, after the embedding model
# could not be reached or was busy.
SEARCH_RETRY_AFTER_SECONDS: Final = 30
# The operation that llm_request_duration_seconds records the query embeddings under.
QUERY_EMBEDDING_OPERATION: Final = "query_embedding"
_SEARCH_UNAVAILABLE_MESSAGE: Final = (
    "Similarity search is unavailable: the embedding model could not embed the query."
)


def normalize_query(text: str) -> str:
    """The query as it is searched for: cleaned like document text, on one line, trimmed.

    Cleaning spells out ligatures and removes control and invisible characters, so a query
    of only those is left empty.
    """
    return " ".join(clean_text(text).split())


class SearchService:
    """Searches a user's workspace for the passages that best match a query."""

    def __init__(self, session: Session, settings: Settings, embedder: EmbeddingProvider) -> None:
        self._session = session
        self._embedder = embedder
        self._workspaces = WorkspaceRepository(session)
        self._store = VectorStore(session)
        self._retriever = Retriever(self._store, min_similarity=settings.search_min_similarity)

    def search(
        self, *, user: User, workspace_id: uuid.UUID, text: str, mode: SearchMode, limit: int
    ) -> SearchResults:
        """At most limit passages of the workspace's ready documents, the best match first.

        hybrid looks for the query's words and for passages whose embeddings are similar to
        the query's; vector only for the latter, keyword only for the former. The query is
        embedded only when some ready document was embedded by the current model. When the
        model fails, a hybrid search goes on with the words alone, and a vector search is
        unavailable.
        """
        # Another user's workspace is reported exactly like a missing one, before any work.
        if self._workspaces.get_for_owner(workspace_id, user.id) is None:
            raise workspace_not_found()
        model = self._embedder.model_name
        scope = self._store.scope(workspace_id, embedding_model=model)
        # No transaction stays open while the query is embedded. commit() rather than
        # rollback(), which would expire the loaded user, and reading it again would start a
        # transaction again.
        self._session.commit()
        query = normalize_query(text)
        vector: list[float] | None = None
        embedding_ms: float | None = None
        # A query that cleaning left empty matches no words, and the OpenAI embedder would
        # refuse it as blank.
        if query and mode != "keyword" and scope.ready_documents > scope.stale_documents:
            started = time.perf_counter()
            vector = self._embed(query, mode)
            embedding_ms = to_ms(time.perf_counter() - started)
        started = time.perf_counter()
        chunks = self._retriever.retrieve(
            workspace_id, query, vector, embedding_model=model, mode=mode, limit=limit
        )
        # Ends the second transaction, and with it the vector list's index scan setting.
        self._session.commit()
        retrieval_seconds = time.perf_counter() - started
        RETRIEVAL_DURATION.labels(mode=mode).observe(retrieval_seconds)
        logger.info(
            "search_completed",
            workspace_id=str(workspace_id),
            mode=mode,
            query_chars=len(query),
            result_count=len(chunks),
            semantic_available=vector is not None,
            embedding_ms=embedding_ms,
            retrieval_ms=to_ms(retrieval_seconds),
        )
        return _results(chunks, scope, semantic_available=vector is not None)

    def _embed(self, query: str, mode: SearchMode) -> list[float] | None:
        """The query's embedding, or None in hybrid mode when the model fails.

        A vector search has nothing to go on without it and is unavailable then.
        """
        started = time.perf_counter()
        try:
            [vector] = self._embedder.embed([query])
        except ProviderError as error:
            _observe_query_embedding("error", started)
            logger.warning("search_embedding_failed", error_code=error.code)
            if mode == "hybrid":
                return None
            raise _search_unavailable(error) from error
        _observe_query_embedding("ok", started)
        return vector


def _observe_query_embedding(outcome: Literal["ok", "error"], started: float) -> None:
    LLM_REQUEST_DURATION.labels(operation=QUERY_EMBEDDING_OPERATION, outcome=outcome).observe(
        time.perf_counter() - started
    )


def _search_unavailable(error: ProviderError) -> ServiceUnavailableError:
    # Waiting helps only when the model could not be reached or was busy; a refusal, such as
    # a spent quota, lasts until someone fixes it.
    headers = {"Retry-After": str(SEARCH_RETRY_AFTER_SECONDS)} if error.transient else None
    return ServiceUnavailableError(
        _SEARCH_UNAVAILABLE_MESSAGE, code="search_unavailable", headers=headers
    )


def _results(
    chunks: Sequence[RetrievedChunk], scope: SearchScope, *, semantic_available: bool
) -> SearchResults:
    return SearchResults(
        results=[_hit(chunk) for chunk in chunks],
        semantic_available=semantic_available,
        searched_document_count=scope.ready_documents,
        stale_document_count=scope.stale_documents,
        pending_document_count=scope.pending_documents,
    )


def _hit(chunk: RetrievedChunk) -> SearchHit:
    return SearchHit(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_title=chunk.document_title,
        chunk_index=chunk.chunk_index,
        heading=chunk.heading,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        snippet=chunk.snippet,
        score=chunk.score,
        matched_by=list(chunk.matched_by),
        similarity=chunk.similarity,
    )
