import os
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Final

import pytest

from app.documents.storage import FileStorage, StorageError

WORKSPACE_ID: Final = uuid.UUID("5b0f8a52-3c1e-4d7a-9f60-2e8b1c4d7a93")
OTHER_WORKSPACE_ID: Final = uuid.UUID("e2a7c3f9-0d4b-4a61-8c5e-7f1b9d3a6c20")
DOCUMENT_ID: Final = uuid.UUID("c41d9e07-6a2b-4f85-b3d1-8e7a5f0c2b64")
CONTENT: Final = "Конспект лекции: интегралы\n".encode()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "uploads"


@pytest.fixture
def storage(root: Path) -> FileStorage:
    return FileStorage(root)


def _store(
    storage: FileStorage,
    content: bytes,
    *,
    workspace_id: uuid.UUID = WORKSPACE_ID,
    document_id: uuid.UUID = DOCUMENT_ID,
) -> str:
    key = storage.key_for(workspace_id, document_id, ".txt")
    with storage.temp_file() as temp:
        temp.write_bytes(content)
        storage.commit_temp(temp, key)
    return key


def _read(storage: FileStorage, key: str) -> bytes:
    with storage.open(key) as stored:
        return stored.read()


def _age(path: Path, minutes: int) -> None:
    modified = time.time() - minutes * 60
    os.utime(path, (modified, modified))


def _fail_while_writing(storage: FileStorage) -> None:
    with storage.temp_file() as temp:
        temp.write_bytes(b"partial upload")
        raise RuntimeError("the client went away")


def test_creating_a_storage_touches_no_files(root: Path) -> None:
    storage = FileStorage(root)

    storage.path_for(storage.key_for(WORKSPACE_ID, DOCUMENT_ID, ".pdf"))

    assert not root.exists()


def test_a_key_is_a_posix_path_built_from_the_ids_alone() -> None:
    key = FileStorage.key_for(WORKSPACE_ID, DOCUMENT_ID, ".pdf")

    assert key == f"{WORKSPACE_ID}/{DOCUMENT_ID}.pdf"


def test_a_key_maps_to_a_native_path_inside_the_root(storage: FileStorage, root: Path) -> None:
    key = storage.key_for(WORKSPACE_ID, DOCUMENT_ID, ".md")

    assert storage.path_for(key) == (root / str(WORKSPACE_ID) / f"{DOCUMENT_ID}.md").resolve()


@pytest.mark.parametrize(
    "key",
    ["../outside.pdf", f"{WORKSPACE_ID}/../../outside.pdf", "/etc/passwd", "..", ".", ""],
    ids=["parent", "nested-parent", "absolute", "dot-dot", "dot", "empty"],
)
def test_a_key_outside_the_root_is_rejected(storage: FileStorage, key: str) -> None:
    with pytest.raises(StorageError):
        storage.path_for(key)


def test_a_temporary_file_is_a_fresh_part_file_in_the_temp_folder(
    storage: FileStorage, root: Path
) -> None:
    with storage.temp_file() as first, storage.temp_file() as second:
        first.write_bytes(b"partial upload")

        assert first.parent == (root / ".tmp").resolve()
        assert first.suffix == ".part"
        assert uuid.UUID(first.stem).version == 4
        assert first != second


def test_a_temporary_file_left_uncommitted_is_removed(storage: FileStorage, root: Path) -> None:
    with storage.temp_file() as temp:
        temp.write_bytes(b"partial upload")

    assert not temp.exists()
    assert list((root / ".tmp").iterdir()) == []


def test_a_temporary_file_is_removed_when_the_upload_fails(
    storage: FileStorage, root: Path
) -> None:
    with pytest.raises(RuntimeError):
        _fail_while_writing(storage)

    assert list((root / ".tmp").iterdir()) == []


def test_a_committed_file_is_read_back_by_its_key(storage: FileStorage, root: Path) -> None:
    key = _store(storage, CONTENT)

    assert _read(storage, key) == CONTENT
    assert (root / str(WORKSPACE_ID) / f"{DOCUMENT_ID}.txt").read_bytes() == CONTENT
    assert list((root / ".tmp").iterdir()) == []


def test_committing_over_a_stored_file_replaces_it_whole(storage: FileStorage) -> None:
    key = _store(storage, b"first version")

    _store(storage, b"second version")

    assert _read(storage, key) == b"second version"


def test_deleting_a_file_twice_reports_whether_it_was_there(storage: FileStorage) -> None:
    key = _store(storage, CONTENT)

    assert storage.delete(key) is True
    assert storage.delete(key) is False
    with pytest.raises(FileNotFoundError):
        storage.open(key)


def test_deleting_a_workspace_twice_removes_only_its_folder(
    storage: FileStorage, root: Path
) -> None:
    _store(storage, b"first", document_id=uuid.uuid4())
    _store(storage, b"second", document_id=uuid.uuid4())
    other_key = _store(storage, b"other", workspace_id=OTHER_WORKSPACE_ID)

    assert storage.delete_workspace(WORKSPACE_ID) is True
    assert storage.delete_workspace(WORKSPACE_ID) is False
    assert not (root / str(WORKSPACE_ID)).exists()
    assert _read(storage, other_key) == b"other"


def test_discarding_a_temporary_file_twice_is_harmless(storage: FileStorage) -> None:
    with storage.temp_file() as temp:
        temp.write_bytes(b"partial upload")

        storage.discard_temp(temp)
        storage.discard_temp(temp)

        assert not temp.exists()


def test_file_operations_refuse_keys_outside_the_root(storage: FileStorage, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_bytes(CONTENT)

    with pytest.raises(StorageError):
        storage.delete("../outside.txt")
    with pytest.raises(StorageError):
        storage.open("../outside.txt")
    assert outside.read_bytes() == CONTENT


def test_only_the_storage_temporary_files_can_be_committed_or_discarded(
    storage: FileStorage, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "notes.part"
    elsewhere.write_bytes(CONTENT)
    key = storage.key_for(WORKSPACE_ID, DOCUMENT_ID, ".txt")

    with pytest.raises(StorageError):
        storage.discard_temp(elsewhere)
    with pytest.raises(StorageError):
        storage.commit_temp(elsewhere, key)
    assert elsewhere.read_bytes() == CONTENT
    with pytest.raises(FileNotFoundError):
        storage.open(key)


def test_sweeping_removes_only_part_files_older_than_an_hour(
    storage: FileStorage, root: Path
) -> None:
    temp_dir = root / ".tmp"
    temp_dir.mkdir(parents=True)
    stale = temp_dir / f"{uuid.uuid4()}.part"
    recent = temp_dir / f"{uuid.uuid4()}.part"
    unrelated = temp_dir / "notes.txt"
    for path in (stale, recent, unrelated):
        path.write_bytes(b"partial upload")
    _age(stale, minutes=61)
    _age(recent, minutes=59)
    _age(unrelated, minutes=24 * 60)
    stored = storage.path_for(_store(storage, CONTENT))
    _age(stored, minutes=24 * 60)

    storage.sweep_temp()

    assert not stale.exists()
    assert recent.exists()
    assert unrelated.exists()
    assert stored.read_bytes() == CONTENT


def test_sweeping_takes_the_age_to_keep(storage: FileStorage) -> None:
    with storage.temp_file() as temp:
        temp.write_bytes(b"partial upload")
        _age(temp, minutes=10)

        storage.sweep_temp(older_than=timedelta(minutes=5))

        assert not temp.exists()


def test_sweeping_without_a_temp_folder_creates_nothing(storage: FileStorage, root: Path) -> None:
    storage.sweep_temp()

    assert not root.exists()
