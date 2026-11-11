import uuid
from typing import Final, Literal

from pydantic import BaseModel, Field

from app.documents.chunking import HEADING_SEPARATOR

# Constants rather than Settings: the request validation they define is fixed when the
# module is imported.
QUERY_MAX_CHARS: Final = 200
DEFAULT_LIMIT: Final = 10
MAX_LIMIT: Final = 20

type SearchMode = Literal["hybrid", "vector", "keyword"]
type MatchKind = Literal["keyword", "semantic"]


class SnippetPart(BaseModel):
    text: str
    highlighted: bool = Field(description="Whether the part is a word that the query matched.")


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str = Field(
        description="The title of the document, or its file name while it has none."
    )
    chunk_index: int = Field(description="Position of the passage in its document, from 0.")
    heading: str | None = Field(
        description="The headings above the passage, outermost first, joined with"
        f" '{HEADING_SEPARATOR}'."
    )
    page_start: int | None = Field(
        description="First PDF page of the passage; null for text files."
    )
    page_end: int | None = Field(description="Last PDF page of the passage; null for text files.")
    snippet: list[SnippetPart] = Field(
        description="Words of the passage in reading order, as plain text parts."
    )
    score: float = Field(description="Reciprocal Rank Fusion score; results come highest first.")
    matched_by: list[MatchKind] = Field(
        description="What found the passage: keyword, the words of the query; semantic, the"
        " similarity of its embedding to the query's."
    )
    similarity: float | None = Field(
        description="Cosine similarity of the passage's embedding to the query's; null when"
        " the passage was not found by its embedding."
    )


class SearchResults(BaseModel):
    results: list[SearchHit]
    semantic_available: bool = Field(
        description="Whether the query was embedded and compared with the embeddings of the"
        " passages; false when only its words were looked for."
    )
    searched_document_count: int = Field(
        description="Ready documents of the workspace: the ones searched."
    )
    stale_document_count: int = Field(
        description="Ready documents embedded by another model than the current one: only"
        " their words are searched until they are re-indexed."
    )
    pending_document_count: int = Field(
        description="Documents still waiting for, or going through, processing: not searched yet."
    )
