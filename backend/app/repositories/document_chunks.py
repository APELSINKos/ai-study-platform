import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session, defer

from app.models.document_chunk import DocumentChunk

CHUNK_INSERT_BATCH_SIZE: Final = 500


@dataclass(frozen=True, slots=True)
class ChunkRow:
    """One chunk to store; the document and workspace ids are added on insert."""

    chunk_index: int
    content: str
    heading: str | None
    page_start: int | None
    page_end: int | None
    char_count: int
    embedding: list[float]


class DocumentChunkRepository:
    """Direct database access for document chunks. Holds no business rules and never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_for_document(
        self, document_id: uuid.UUID, workspace_id: uuid.UUID, rows: Sequence[ChunkRow]
    ) -> None:
        self._session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        for start in range(0, len(rows), CHUNK_INSERT_BATCH_SIZE):
            batch = rows[start : start + CHUNK_INSERT_BATCH_SIZE]
            self._session.execute(
                insert(DocumentChunk),
                [
                    {
                        "document_id": document_id,
                        "workspace_id": workspace_id,
                        "chunk_index": row.chunk_index,
                        "content": row.content,
                        "heading": row.heading,
                        "page_start": row.page_start,
                        "page_end": row.page_end,
                        "char_count": row.char_count,
                        "embedding": row.embedding,
                    }
                    for row in batch
                ],
            )

    def list_for_document(
        self, document_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[DocumentChunk], int]:
        statement = (
            select(DocumentChunk)
            .options(
                # Touching these afterwards raises instead of quietly loading every vector.
                defer(DocumentChunk.embedding, raiseload=True),
                defer(DocumentChunk.search_vector, raiseload=True),
            )
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
            .offset(offset)
            .limit(limit)
        )
        chunks = list(self._session.execute(statement).scalars())
        total_statement = (
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        return chunks, self._session.execute(total_statement).scalar_one()
