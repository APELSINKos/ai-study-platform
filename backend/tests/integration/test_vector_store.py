import hashlib
import math
import re
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Connection, event, select, text
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace
from app.rag.vector_store import (
    HIGHLIGHT_START,
    HIGHLIGHT_STOP,
    MAX_KEYWORD_QUERY_CHARS,
    ChunkHit,
    KeywordCandidate,
    SearchScope,
    VectorCandidate,
    VectorStore,
)
from app.repositories.document_chunks import ChunkRow, DocumentChunkRepository
from app.repositories.documents import DocumentRepository
from app.repositories.users import UserRepository
from app.repositories.workspaces import WorkspaceRepository

pytestmark = pytest.mark.integration

_NOW: Final = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
_MODEL: Final = "mock-hashing-v1"
_OTHER_MODEL: Final = "text-embedding-3-small"
_LIMIT: Final = 40
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {"chunk_count": 1, "embedding_model": _MODEL, "processed_at": _NOW},
    "failed": {"error_code": "no_text"},
}
_MARKED_RE: Final = re.compile(
    f"{HIGHLIGHT_START}([^{HIGHLIGHT_START}{HIGHLIGHT_STOP}]*){HIGHLIGHT_STOP}"
)
HOSTILE_TEXT_LENGTH: Final = 2_000_000
# Timed with coverage's tracer paused (no_cover): tracing multiplies the time of every step.
HOSTILE_TIME_LIMIT_SECONDS: Final = 2.0


def _workspace(session: Session, name: str = "Biology") -> Workspace:
    """A workspace of an owner of its own."""
    owner = UserRepository(session).add(
        User(
            email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="hash",
            display_name="Owner",
        )
    )
    return WorkspaceRepository(session).add(Workspace(owner_id=owner.id, name=name))


def _document(
    session: Session, workspace: Workspace, status: DocumentStatus = "ready", **values: object
) -> Document:
    document_id = uuid.uuid4()
    fields: dict[str, object] = {
        "id": document_id,
        "workspace_id": workspace.id,
        "original_filename": "notes.md",
        "content_type": "text/markdown",
        "size_bytes": 1024,
        "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
        "storage_key": f"{workspace.id}/{document_id}.md",
        "status": status,
        **_STATUS_FIELDS.get(status, {}),
    }
    fields.update(values)
    return DocumentRepository(session).add(Document(**fields))


def _one_hot(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


def _unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(component * component for component in vector))
    return [component / norm for component in vector]


def _row(index: int, content: str, *, embedding: list[float] | None = None) -> ChunkRow:
    return ChunkRow(
        chunk_index=index,
        content=content,
        heading=None,
        page_start=None,
        page_end=None,
        char_count=len(content),
        embedding=_one_hot(index) if embedding is None else embedding,
    )


def _store(session: Session, document: Document, *rows: ChunkRow) -> list[uuid.UUID]:
    """Store the rows as the document's chunks; their ids, in the order of the rows."""
    DocumentChunkRepository(session).replace_for_document(document.id, document.workspace_id, rows)
    statement = select(DocumentChunk.chunk_index, DocumentChunk.id).where(
        DocumentChunk.document_id == document.id
    )
    ids = {stored.chunk_index: stored.id for stored in session.execute(statement)}
    return [ids[row.chunk_index] for row in rows]


def _texts(session: Session, document: Document, *contents: str) -> list[uuid.UUID]:
    return _store(
        session, document, *(_row(index, content) for index, content in enumerate(contents))
    )


def _ids(items: Sequence[VectorCandidate | KeywordCandidate | ChunkHit]) -> list[uuid.UUID]:
    return [item.chunk_id for item in items]


def _marked(headline: str) -> list[str]:
    return _MARKED_RE.findall(headline)


def _iterative_scan(session: Session) -> str | None:
    return session.execute(text("SELECT current_setting('hnsw.iterative_scan', true)")).scalar()


def test_every_query_keeps_to_its_workspace(db_session: Session) -> None:
    store = VectorStore(db_session)
    mine = _workspace(db_session)
    theirs = _workspace(db_session)
    (my_chunk,) = _texts(db_session, _document(db_session, mine), "Photosynthesis needs light.")
    (their_chunk,) = _texts(
        db_session, _document(db_session, theirs), "Photosynthesis needs light."
    )
    _document(db_session, theirs, "uploaded")

    nearest = store.nearest(mine.id, _one_hot(0), embedding_model=_MODEL, limit=_LIMIT)
    matching = store.matching(mine.id, "photosynthesis", limit=_LIMIT)
    # The ids come from the caller: one of another workspace is left out.
    hits = store.hits(mine.id, [their_chunk, my_chunk], "photosynthesis")

    assert _ids(nearest) == _ids(matching) == _ids(hits) == [my_chunk]
    assert store.scope(mine.id, embedding_model=_MODEL) == SearchScope(
        ready_documents=1, stale_documents=0, pending_documents=0
    )


@pytest.mark.parametrize("status", ["uploaded", "processing", "indexing", "failed"])
def test_chunks_of_a_document_that_is_not_ready_are_not_searched(
    db_session: Session, status: DocumentStatus
) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    # A document processed again, or whose next run failed, keeps the chunks of its last run.
    document = _document(db_session, workspace, status, embedding_model=_MODEL)
    _texts(db_session, document, "Photosynthesis needs light.")

    assert store.nearest(workspace.id, _one_hot(0), embedding_model=_MODEL, limit=_LIMIT) == []
    assert store.matching(workspace.id, "photosynthesis", limit=_LIMIT) == []


def test_a_document_embedded_by_another_model_is_searched_by_its_words_only(
    db_session: Session,
) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    (current,) = _texts(db_session, _document(db_session, workspace), "Photosynthesis needs light.")
    stale_document = _document(db_session, workspace, embedding_model=_OTHER_MODEL)
    # The same vector as the query: only the model tells the two apart.
    (stale,) = _texts(db_session, stale_document, "Photosynthesis makes sugar.")

    nearest = store.nearest(workspace.id, _one_hot(0), embedding_model=_MODEL, limit=_LIMIT)
    matching = store.matching(workspace.id, "photosynthesis", limit=_LIMIT)

    assert _ids(nearest) == [current]
    assert set(_ids(matching)) == {current, stale}
    assert store.scope(workspace.id, embedding_model=_MODEL) == SearchScope(
        ready_documents=2, stale_documents=1, pending_documents=0
    )


def test_scope_counts_the_ready_stale_and_pending_documents_of_the_workspace(
    db_session: Session,
) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    other = _workspace(db_session)
    for status in ("ready", "ready", "uploaded", "processing", "indexing", "failed", "failed"):
        _document(db_session, workspace, status)
    _document(db_session, workspace, embedding_model=_OTHER_MODEL)
    _document(db_session, other)
    _document(db_session, other, "processing")

    assert store.scope(workspace.id, embedding_model=_MODEL) == SearchScope(
        ready_documents=3, stale_documents=1, pending_documents=3
    )
    assert store.scope(uuid.uuid4(), embedding_model=_MODEL) == SearchScope(
        ready_documents=0, stale_documents=0, pending_documents=0
    )


def test_a_document_filter_keeps_every_query_to_those_documents(db_session: Session) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    chosen = _document(db_session, workspace)
    (chosen_chunk,) = _texts(db_session, chosen, "Photosynthesis needs light.")
    _texts(db_session, _document(db_session, workspace), "Photosynthesis makes sugar.")
    _document(db_session, workspace, "uploaded")
    only = [chosen.id]

    nearest = store.nearest(
        workspace.id, _one_hot(0), embedding_model=_MODEL, limit=_LIMIT, document_ids=only
    )
    matching = store.matching(workspace.id, "photosynthesis", limit=_LIMIT, document_ids=only)

    assert _ids(nearest) == _ids(matching) == [chosen_chunk]
    assert store.scope(workspace.id, embedding_model=_MODEL, document_ids=only) == SearchScope(
        ready_documents=1, stale_documents=0, pending_documents=0
    )


def test_an_empty_document_filter_matches_nothing(db_session: Session) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    _texts(db_session, _document(db_session, workspace), "Photosynthesis needs light.")

    nearest = store.nearest(
        workspace.id, _one_hot(0), embedding_model=_MODEL, limit=_LIMIT, document_ids=[]
    )
    matching = store.matching(workspace.id, "photosynthesis", limit=_LIMIT, document_ids=[])

    assert nearest == []
    assert matching == []
    assert store.scope(workspace.id, embedding_model=_MODEL, document_ids=[]) == SearchScope(
        ready_documents=0, stale_documents=0, pending_documents=0
    )


def test_nearest_puts_the_closest_chunks_first_and_breaks_ties_by_id(db_session: Session) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    document = _document(db_session, workspace)
    between = _unit([1.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2))
    # Six chunks at the same distance: their random ids are in the order they were stored
    # once in 720 runs.
    *tied, same, near = _store(
        db_session,
        document,
        *(_row(index, f"Unrelated passage {index}.") for index in range(2, 8)),
        _row(0, "Photosynthesis needs light."),
        _row(1, "Light reactions make oxygen.", embedding=between),
    )

    found = store.nearest(workspace.id, _one_hot(0), embedding_model=_MODEL, limit=_LIMIT)
    first_two = store.nearest(workspace.id, _one_hot(0), embedding_model=_MODEL, limit=2)

    assert _ids(found) == [same, near, *sorted(tied)]
    assert [candidate.distance for candidate in found] == pytest.approx(
        [0, 1 - 1 / math.sqrt(2), 1, 1, 1, 1, 1, 1]
    )
    assert {candidate.document_id for candidate in found} == {document.id}
    assert _ids(first_two) == [same, near]


def test_matching_ranks_chunks_by_their_words_and_breaks_ties_by_id(db_session: Session) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    document = _document(db_session, workspace)
    *tied, _, three_times = _texts(
        db_session,
        document,
        *(["Light and water."] * 6),
        "Water and sugar.",
        "Light, more light and still more light.",
    )

    found = store.matching(workspace.id, "light", limit=_LIMIT)
    first = store.matching(workspace.id, "light", limit=1)

    assert _ids(found) == [three_times, *sorted(tied)]
    assert found[0].rank > found[1].rank > 0
    assert len({candidate.rank for candidate in found[1:]}) == 1
    assert {candidate.document_id for candidate in found} == {document.id}
    assert _ids(first) == [three_times]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ('"light reaction"', [0]),
        ("light reaction", [0, 1]),
        ("thylakoid or mitochondria", [0, 2]),
        ("reaction -eye", [0]),
    ],
    ids=["phrase", "all-words", "either-word", "excluded-word"],
)
def test_matching_reads_the_query_as_a_web_search(
    db_session: Session, query: str, expected: list[int]
) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    ids = _texts(
        db_session,
        _document(db_session, workspace),
        "The light reaction takes place in the thylakoid membranes.",
        "The reaction of an eye to light is fast.",
        "Cellular respiration happens in the mitochondria.",
    )

    found = store.matching(workspace.id, query, limit=_LIMIT)

    assert set(_ids(found)) == {ids[index] for index in expected}


@pytest.mark.parametrize("query", ["", "   ", "!!!", "?!,.;:", '""', "-light", "-light -water"])
def test_a_query_without_words_or_with_excluded_words_only_matches_nothing(
    db_session: Session, query: str
) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    _texts(db_session, _document(db_session, workspace), "Light and water.", "Sugar and starch.")

    assert store.matching(workspace.id, query, limit=_LIMIT) == []


def test_a_long_query_is_cut_before_the_word_that_the_limit_falls_in(db_session: Session) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    (chunk,) = _texts(
        db_session, _document(db_session, workspace), "Photosynthesis turns light into sugar."
    )
    # 2,100 characters: one word repeated past the limit, then a word that no chunk has,
    # which would make the query match nothing if it were kept.
    query = "photosynthesis " * 20 + "zebra " * 300
    sent: list[str] = []

    def record_query_text(**event_args: Any) -> None:
        sent.extend(
            value
            for value in event_args["parameters"].values()
            if isinstance(value, str) and "photosynthesis" in value
        )

    event.listen(db_session.connection(), "before_cursor_execute", record_query_text, named=True)

    found = store.matching(workspace.id, query, limit=_LIMIT)
    (hit,) = store.hits(workspace.id, [chunk], query)

    assert _ids(found) == [chunk]
    assert _marked(hit.headline) == ["Photosynthesis"]
    assert len(sent) == 2
    for value in sent:
        assert len(value) <= MAX_KEYWORD_QUERY_CHARS
        assert value.split() == ["photosynthesis"] * 17


@pytest.mark.parametrize(
    "signs", ["-" * 40, "- " * 40, "-!" * 40], ids=["minus", "minus-space", "minus-operator"]
)
def test_minus_signs_in_a_row_cancel_out_in_pairs(db_session: Session, signs: str) -> None:
    # Each sign is a NOT waiting for the next word, and PostgreSQL fails beyond 32 of them.
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    with_water, with_sugar = _texts(
        db_session, _document(db_session, workspace), "Light and water.", "Light and sugar."
    )

    even = store.matching(workspace.id, f"light {signs}sugar", limit=_LIMIT)
    odd = store.matching(workspace.id, f"light -{signs}sugar", limit=_LIMIT)

    assert _ids(even) == [with_sugar]
    assert _ids(odd) == [with_water]


@pytest.mark.no_cover
@pytest.mark.parametrize("unit", ["x", " ", "-", "- ", "-!", '"', "light "])
def test_a_hostile_query_of_two_million_characters_is_answered_quickly(
    db_session: Session, unit: str
) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    (chunk,) = _texts(db_session, _document(db_session, workspace), "Light and water.")
    query = (unit * HOSTILE_TEXT_LENGTH)[:HOSTILE_TEXT_LENGTH]

    started = time.perf_counter()
    store.matching(workspace.id, query, limit=_LIMIT)
    store.hits(workspace.id, [chunk], query)

    assert time.perf_counter() - started < HOSTILE_TIME_LIMIT_SECONDS


def test_russian_words_match_in_any_letter_case(db_session: Session) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    light, dark = _texts(
        db_session,
        _document(db_session, workspace),
        "Световая фаза идёт на мембранах тилакоидов.",
        "Темновая фаза идёт в строме хлоропласта.",
    )

    assert _ids(store.matching(workspace.id, "световая фаза", limit=_LIMIT)) == [light]
    assert _ids(store.matching(workspace.id, '"темновая фаза"', limit=_LIMIT)) == [dark]
    assert set(_ids(store.matching(workspace.id, "ФАЗА", limit=_LIMIT))) == {light, dark}
    (hit,) = store.hits(workspace.id, [light], "световая фаза")
    assert _marked(hit.headline) == ["Световая", "фаза"]


def test_hits_return_the_chunks_with_their_document_titles_and_places(
    db_session: Session,
) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    lecture = _document(
        db_session,
        workspace,
        title="Photosynthesis",
        original_filename="lecture.pdf",
        content_type="application/pdf",
    )
    notes = _document(db_session, workspace, original_filename="notes.md")
    content = "Light reactions make oxygen."
    with_place = ChunkRow(
        chunk_index=3,
        content=content,
        heading="Light reactions",
        page_start=4,
        page_end=5,
        char_count=len(content),
        embedding=_one_hot(3),
    )
    (in_lecture,) = _store(db_session, lecture, with_place)
    (in_notes,) = _texts(db_session, notes, "Plain notes on light.")

    # Any order in; an id that matches no chunk, such as a deleted one's, is left out.
    found = store.hits(workspace.id, [in_notes, uuid.uuid4(), in_lecture], "light")

    hits = {hit.chunk_id: hit for hit in found}
    assert hits.keys() == {in_lecture, in_notes}
    lecture_hit = hits[in_lecture]
    assert (
        lecture_hit.document_id,
        lecture_hit.document_title,
        lecture_hit.chunk_index,
        lecture_hit.heading,
        lecture_hit.page_start,
        lecture_hit.page_end,
        lecture_hit.content,
        lecture_hit.char_count,
    ) == (lecture.id, "Photosynthesis", 3, "Light reactions", 4, 5, content, len(content))
    notes_hit = hits[in_notes]
    # A document without a title yet is shown by its file name.
    assert (
        notes_hit.document_id,
        notes_hit.document_title,
        notes_hit.heading,
        notes_hit.page_start,
        notes_hit.page_end,
    ) == (notes.id, "notes.md", None, None, None)


def test_hits_mark_the_words_of_the_query_only_in_chunks_that_they_match(
    db_session: Session,
) -> None:
    store = VectorStore(db_session)
    workspace = _workspace(db_session)
    contents = (
        "The light reaction takes place in the thylakoid membranes.",
        "The reaction of an eye to light is fast.",
        "Cellular respiration happens in the mitochondria of every living cell.",
    )
    matching, excluded, unrelated = _texts(db_session, _document(db_session, workspace), *contents)

    found = store.hits(workspace.id, [matching, excluded, unrelated], "light reaction -eye")

    headlines = {hit.chunk_id: hit.headline for hit in found}
    assert _marked(headlines[matching]) == ["light", "reaction"]
    # A chunk that the words do not match, found by its embedding alone, shows its first
    # words unmarked: not even a word of the query that it does contain is marked.
    for chunk, content in ((excluded, contents[1]), (unrelated, contents[2])):
        headline = headlines[chunk]
        assert headline
        assert HIGHLIGHT_START not in headline
        assert HIGHLIGHT_STOP not in headline
        assert content.startswith(headline)


def test_nearest_turns_iterative_index_scans_on_for_the_rest_of_the_transaction(
    db_session: Session,
) -> None:
    assert _iterative_scan(db_session) != "relaxed_order"

    VectorStore(db_session).nearest(uuid.uuid4(), _one_hot(0), embedding_model=_MODEL, limit=_LIMIT)

    assert _iterative_scan(db_session) == "relaxed_order"


def test_the_iterative_scan_setting_ends_with_its_transaction(db_connection: Connection) -> None:
    # A connection of its own: the test's usual one stays in a single transaction throughout.
    with db_connection.engine.connect() as connection, Session(bind=connection) as session:
        VectorStore(session).nearest(
            uuid.uuid4(), _one_hot(0), embedding_model=_MODEL, limit=_LIMIT
        )
        session.commit()

        assert _iterative_scan(session) == "off"
