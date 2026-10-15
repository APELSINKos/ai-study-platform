import hashlib
import uuid
from datetime import UTC, datetime
from typing import Final

import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models.document import (
    DIFFICULTIES,
    DOCUMENT_CONTENT_TYPES,
    DOCUMENT_ERROR_CODES,
    DOCUMENT_STATUSES,
    Document,
)
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace

pytestmark = pytest.mark.integration

_PROCESSED_AT: Final = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _user(session: Session, email: str = "owner@example.com") -> User:
    user = User(email=email, password_hash="hash", display_name="Owner")
    _flush(session, user)
    return user


def _workspace(session: Session, owner: User, name: str = "Algorithms") -> Workspace:
    workspace = Workspace(owner_id=owner.id, name=name)
    _flush(session, workspace)
    return workspace


def _document(workspace: Workspace, **overrides: object) -> Document:
    document_id = uuid.uuid4()
    values: dict[str, object] = {
        "id": document_id,
        "workspace_id": workspace.id,
        "original_filename": "notes.md",
        "content_type": "text/markdown",
        "size_bytes": 2048,
        "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
        "storage_key": f"{workspace.id}/{document_id}.md",
    }
    values.update(overrides)
    return Document(**values)


def _unit_embedding() -> list[float]:
    return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


def _chunk(document: Document, **overrides: object) -> DocumentChunk:
    values: dict[str, object] = {
        "document_id": document.id,
        "workspace_id": document.workspace_id,
        "chunk_index": 0,
        "content": "Binary search halves the interval.",
        "char_count": 34,
        "embedding": _unit_embedding(),
    }
    values.update(overrides)
    return DocumentChunk(**values)


def _flush(session: Session, *rows: object) -> None:
    session.add_all(rows)
    session.flush()


def _violated_constraint(error: IntegrityError) -> str | None:
    assert isinstance(error.orig, psycopg.Error)
    return error.orig.diag.constraint_name


def test_a_new_document_is_uploaded_with_no_attempts(db_session: Session) -> None:
    document = _document(_workspace(db_session, _user(db_session)))

    _flush(db_session, document)

    assert document.status == "uploaded"
    assert document.attempts == 0


def test_complete_ready_and_failed_documents_are_accepted(db_session: Session) -> None:
    workspace = _workspace(db_session, _user(db_session))
    ready = _document(
        workspace,
        status="ready",
        attempts=1,
        title="Sorting",
        summary="Comparison sorts and their bounds.",
        topics=["sorting", "complexity"],
        difficulty="medium",
        estimated_study_minutes=12,
        page_count=4,
        word_count=1800,
        chunk_count=3,
        processing_ms=950,
        analysis_model="mock-heuristic-v1",
        embedding_model="mock-hashing-v1",
        processing_started_at=_PROCESSED_AT,
        processed_at=_PROCESSED_AT,
    )
    failed = _document(
        workspace, status="failed", error_code="pdf_unreadable", error_message="Broken file."
    )

    _flush(db_session, ready, failed)
    db_session.expire_all()

    assert ready.topics == ["sorting", "complexity"]
    assert failed.error_code == "pdf_unreadable"


def test_every_declared_value_is_accepted(db_session: Session) -> None:
    workspace = _workspace(db_session, _user(db_session))
    complete = {"chunk_count": 1, "embedding_model": "m", "processed_at": _PROCESSED_AT}

    _flush(
        db_session,
        *(
            _document(workspace, status=status, error_code="internal_error", **complete)
            for status in DOCUMENT_STATUSES
        ),
        *(
            _document(workspace, content_type=content_type)
            for content_type in DOCUMENT_CONTENT_TYPES
        ),
        *(_document(workspace, difficulty=difficulty) for difficulty in DIFFICULTIES),
        *(_document(workspace, status="failed", error_code=code) for code in DOCUMENT_ERROR_CODES),
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"status": "archived"}, "ck_documents_status_valid", id="status"),
        pytest.param(
            {"content_type": "application/msword"},
            "ck_documents_content_type_valid",
            id="content-type",
        ),
        pytest.param({"difficulty": "extreme"}, "ck_documents_difficulty_valid", id="difficulty"),
        pytest.param({"error_code": "disk_full"}, "ck_documents_error_code_valid", id="error-code"),
        pytest.param({"size_bytes": 0}, "ck_documents_size_bytes_positive", id="size"),
        pytest.param({"attempts": -1}, "ck_documents_attempts_non_negative", id="attempts"),
        pytest.param({"sha256": "A" * 64}, "ck_documents_sha256_hex", id="sha256-uppercase"),
        pytest.param({"sha256": "a" * 63}, "ck_documents_sha256_hex", id="sha256-short"),
        pytest.param({"topics": {"topic": "sorting"}}, "ck_documents_topics_array", id="topics"),
        pytest.param({"status": "failed"}, "ck_documents_failed_has_error_code", id="failed"),
        pytest.param(
            {"status": "ready", "embedding_model": "m", "processed_at": _PROCESSED_AT},
            "ck_documents_ready_is_complete",
            id="ready-without-chunk-count",
        ),
        pytest.param(
            {"status": "ready", "chunk_count": 3, "processed_at": _PROCESSED_AT},
            "ck_documents_ready_is_complete",
            id="ready-without-embedding-model",
        ),
        pytest.param(
            {"status": "ready", "chunk_count": 3, "embedding_model": "m"},
            "ck_documents_ready_is_complete",
            id="ready-without-processed-at",
        ),
        pytest.param({"page_count": -1}, "ck_documents_counts_non_negative", id="page-count"),
        pytest.param({"word_count": -1}, "ck_documents_counts_non_negative", id="word-count"),
        pytest.param({"chunk_count": -1}, "ck_documents_counts_non_negative", id="chunk-count"),
        pytest.param({"processing_ms": -1}, "ck_documents_counts_non_negative", id="processing"),
        pytest.param(
            {"estimated_study_minutes": -1}, "ck_documents_counts_non_negative", id="minutes"
        ),
    ],
)
def test_document_checks_reject_a_bad_row(
    db_session: Session, overrides: dict[str, object], constraint: str
) -> None:
    workspace = _workspace(db_session, _user(db_session))

    with pytest.raises(IntegrityError) as caught:
        _flush(db_session, _document(workspace, **overrides))

    assert _violated_constraint(caught.value) == constraint


def test_chunks_with_and_without_a_page_range_are_accepted(db_session: Session) -> None:
    document = _document(_workspace(db_session, _user(db_session)))
    _flush(db_session, document)

    _flush(
        db_session,
        _chunk(document, chunk_index=0, page_start=2, page_end=2),
        _chunk(document, chunk_index=1, page_start=2, page_end=5),
        _chunk(document, chunk_index=2),
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param(
            {"chunk_index": -1}, "ck_document_chunks_chunk_index_non_negative", id="index"
        ),
        pytest.param({"char_count": 0}, "ck_document_chunks_char_count_positive", id="chars"),
        pytest.param(
            {"page_start": 0, "page_end": 1},
            "ck_document_chunks_page_range_valid",
            id="page-zero",
        ),
        pytest.param(
            {"page_start": 3, "page_end": 2},
            "ck_document_chunks_page_range_valid",
            id="page-inverted",
        ),
        pytest.param(
            {"page_start": 2, "page_end": None},
            "ck_document_chunks_page_range_valid",
            id="page-end-missing",
        ),
        pytest.param(
            {"page_start": None, "page_end": 2},
            "ck_document_chunks_page_range_valid",
            id="page-start-missing",
        ),
    ],
)
def test_chunk_checks_reject_a_bad_row(
    db_session: Session, overrides: dict[str, object], constraint: str
) -> None:
    document = _document(_workspace(db_session, _user(db_session)))
    _flush(db_session, document)

    with pytest.raises(IntegrityError) as caught:
        _flush(db_session, _chunk(document, **overrides))

    assert _violated_constraint(caught.value) == constraint


def test_an_embedding_of_the_wrong_size_is_rejected(db_session: Session) -> None:
    document = _document(_workspace(db_session, _user(db_session)))
    _flush(db_session, document)

    with pytest.raises(DataError):
        _flush(db_session, _chunk(document, embedding=[1.0, 0.0, 0.0]))


def test_search_vector_indexes_the_heading_and_content_without_stemming(
    db_session: Session,
) -> None:
    document = _document(_workspace(db_session, _user(db_session)))
    chunk = _chunk(
        document, heading="Глава 2 \u203a Sorting", content="Студенты изучают running algorithms"
    )
    _flush(db_session, document)
    _flush(db_session, chunk)

    row = db_session.execute(
        text(
            "SELECT search_vector = to_tsvector('simple', CAST(:expected AS text)),"
            " search_vector @@ to_tsquery('simple', 'running'),"
            " search_vector @@ to_tsquery('simple', 'run'),"
            " search_vector @@ to_tsquery('simple', 'студенты'),"
            " search_vector @@ to_tsquery('simple', 'студент'),"
            " search_vector @@ to_tsquery('simple', 'глава')"
            " FROM document_chunks WHERE id = :id"
        ),
        {"expected": "Глава 2 \u203a Sorting Студенты изучают running algorithms", "id": chunk.id},
    ).one()

    assert tuple(row) == (True, True, False, True, False, True)


def test_search_vector_of_a_chunk_without_a_heading_is_its_content(db_session: Session) -> None:
    document = _document(_workspace(db_session, _user(db_session)))
    chunk = _chunk(document, heading=None, content="Hash tables trade memory for speed")
    _flush(db_session, document)
    _flush(db_session, chunk)

    matches: bool = db_session.execute(
        text(
            "SELECT search_vector = to_tsvector('simple', content)"
            " FROM document_chunks WHERE id = :id"
        ),
        {"id": chunk.id},
    ).scalar_one()

    assert matches is True


def test_chunks_have_an_hnsw_cosine_index_and_a_gin_full_text_index(db_session: Session) -> None:
    rows = db_session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'document_chunks'")
    )
    definitions = {row.indexname: row.indexdef for row in rows}

    hnsw = definitions["ix_document_chunks_embedding_hnsw"]
    assert "USING hnsw (embedding vector_cosine_ops)" in hnsw
    assert "WITH (m='16', ef_construction='64')" in hnsw
    assert "USING gin (search_vector)" in definitions["ix_document_chunks_search_vector"]


def test_a_chunk_cannot_belong_to_another_workspace_than_its_document(
    db_session: Session,
) -> None:
    owner = _user(db_session)
    home = _workspace(db_session, owner, "Home")
    other = _workspace(db_session, owner, "Other")
    document = _document(home)
    _flush(db_session, document)

    with pytest.raises(IntegrityError) as caught:
        _flush(db_session, _chunk(document, workspace_id=other.id))

    assert _violated_constraint(caught.value) == "fk_document_chunks_document_id_documents"


def test_a_chunk_index_is_unique_within_its_document(db_session: Session) -> None:
    document = _document(_workspace(db_session, _user(db_session)))
    _flush(db_session, document)
    _flush(db_session, _chunk(document, chunk_index=4))

    with pytest.raises(IntegrityError) as caught:
        _flush(db_session, _chunk(document, chunk_index=4))

    assert _violated_constraint(caught.value) == "uq_document_chunks_document_id_chunk_index"


def test_the_same_file_is_accepted_once_per_workspace(db_session: Session) -> None:
    owner = _user(db_session)
    first = _workspace(db_session, owner, "First")
    second = _workspace(db_session, owner, "Second")
    digest = "ab" * 32
    _flush(db_session, _document(first, sha256=digest), _document(second, sha256=digest))

    with pytest.raises(IntegrityError) as caught:
        _flush(db_session, _document(first, sha256=digest))

    assert _violated_constraint(caught.value) == "uq_documents_workspace_id_sha256"


def test_storage_keys_are_unique(db_session: Session) -> None:
    workspace = _workspace(db_session, _user(db_session))
    key = f"{workspace.id}/{uuid.uuid4()}.md"
    _flush(db_session, _document(workspace, storage_key=key))

    with pytest.raises(IntegrityError) as caught:
        _flush(db_session, _document(workspace, storage_key=key))

    assert _violated_constraint(caught.value) == "uq_documents_storage_key"


def test_deleting_a_workspace_removes_its_documents_and_chunks(db_session: Session) -> None:
    owner = _user(db_session)
    removed = _workspace(db_session, owner, "Removed")
    kept = _workspace(db_session, owner, "Kept")
    removed_document = _document(removed)
    kept_document = _document(kept)
    _flush(db_session, removed_document, kept_document)
    _flush(db_session, _chunk(removed_document), _chunk(kept_document))
    document_ids = [removed_document.id, kept_document.id]

    db_session.delete(removed)
    db_session.flush()

    remaining_documents = db_session.scalars(
        select(Document.id).where(Document.id.in_(document_ids))
    ).all()
    remaining_chunk_documents = db_session.scalars(
        select(DocumentChunk.document_id).where(DocumentChunk.document_id.in_(document_ids))
    ).all()
    assert remaining_documents == [kept_document.id]
    assert remaining_chunk_documents == [kept_document.id]


def test_deleting_a_user_removes_their_workspaces_documents_and_chunks(
    db_session: Session,
) -> None:
    owner = _user(db_session)
    workspace = _workspace(db_session, owner)
    document = _document(workspace)
    _flush(db_session, document)
    _flush(db_session, _chunk(document))

    db_session.delete(owner)
    db_session.flush()

    assert db_session.scalars(select(Workspace.id).where(Workspace.id == workspace.id)).all() == []
    assert db_session.scalars(select(Document.id).where(Document.id == document.id)).all() == []
    assert (
        db_session.scalars(
            select(DocumentChunk.id).where(DocumentChunk.document_id == document.id)
        ).all()
        == []
    )
