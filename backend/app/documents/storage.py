import os
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO, Final

TEMP_DIR_NAME: Final = ".tmp"
TEMP_FILE_SUFFIX: Final = ".part"
# Copying an upload to disk takes seconds, so an older .part file is from a request that died.
STALE_TEMP_FILE_AGE: Final = timedelta(hours=1)


class StorageError(Exception):
    """A key or a temporary path that does not belong to the storage."""


class FileStorage:
    """Uploaded files under one root directory, addressed by POSIX keys.

    Nothing touches the filesystem until the first write, so the app can be created
    where the root does not exist (CI, the OpenAPI export, unit tests).
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def key_for(workspace_id: uuid.UUID, document_id: uuid.UUID, extension: str) -> str:
        # Built from ids alone: the user's file name never becomes part of a path.
        return f"{workspace_id}/{document_id}{extension}"

    def path_for(self, key: str) -> Path:
        """The absolute path of a key; it must lie inside the root, never be the root."""
        root = self._root.resolve()
        path = (root / key).resolve()
        if path == root or not path.is_relative_to(root):
            raise StorageError(f"The key {key!r} does not name a file inside the storage root.")
        return path

    @contextmanager
    def temp_file(self) -> Iterator[Path]:
        """Yield a fresh .part path for an upload in progress; a file left there is removed."""
        directory = self._temp_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid.uuid4()}{TEMP_FILE_SUFFIX}"
        try:
            yield path
        finally:
            self.discard_temp(path)

    def commit_temp(self, temp_path: Path, key: str) -> None:
        """Move a finished upload to its key; os.replace makes the move atomic."""
        source = self._own_temp_file(temp_path)
        destination = self.path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    def open(self, key: str) -> BinaryIO:
        return self.path_for(key).open("rb")

    def delete(self, key: str) -> bool:
        """Remove a stored file; False when it was already gone."""
        try:
            self.path_for(key).unlink()
        except FileNotFoundError:
            return False
        return True

    def delete_workspace(self, workspace_id: uuid.UUID) -> bool:
        """Remove a workspace's folder with every file in it; False when there was none."""
        try:
            shutil.rmtree(self.path_for(str(workspace_id)))
        except FileNotFoundError:
            return False
        return True

    def discard_temp(self, path: Path) -> None:
        self._own_temp_file(path).unlink(missing_ok=True)

    def sweep_temp(self, older_than: timedelta = STALE_TEMP_FILE_AGE) -> None:
        """Remove .part files older than older_than, left by uploads that never finished."""
        cutoff = time.time() - older_than.total_seconds()
        for path in self._temp_dir().glob(f"*{TEMP_FILE_SUFFIX}"):
            # Two uploads may sweep at the same time; either one removing a file is enough.
            with suppress(FileNotFoundError):
                if path.stat().st_mtime < cutoff:
                    path.unlink()

    def _temp_dir(self) -> Path:
        return self._root.resolve() / TEMP_DIR_NAME

    def _own_temp_file(self, path: Path) -> Path:
        if path.suffix != TEMP_FILE_SUFFIX or path.parent.resolve() != self._temp_dir():
            raise StorageError(f"{path} is not a temporary file of this storage.")
        return path
