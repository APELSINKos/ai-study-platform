import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from app.documents.extraction import MAX_PDF_STREAM_BYTES
from app.workers.celery_app import WORKER_CHILD_MEMORY_LIMIT_BYTES
from tests.fixtures.pdf_builder import many_fonts_pdf

BACKEND_DIR: Final = Path(__file__).resolve().parents[2]
# A new worker child: the app imported, then the signal Celery sends as the child starts.
_EXTRACT_IN_A_NEW_CHILD: Final = """
import sys
from pathlib import Path

from celery import signals

import app.workers.tasks
from app.documents.errors import DocumentProcessingError
from app.documents.extraction import extract

signals.worker_process_init.send(sender=None)
try:
    extract(
        Path(sys.argv[1]),
        "application/pdf",
        max_pdf_pages=500,
        max_chars=2_000_000,
        check_deadline=lambda: None,
    )
    print("extracted")
except DocumentProcessingError as error:
    print(error.code)
"""


@pytest.mark.skipif(sys.platform == "win32", reason="memory limits are set the POSIX way")
def test_a_pdf_that_needs_more_memory_than_a_worker_child_has_is_unreadable(
    tmp_path: Path,
) -> None:
    # Each font's map stays within the stream limit, but pypdf keeps all of them: together
    # they need more than a child may use, from a file of under a mebibyte.
    map_bytes = MAX_PDF_STREAM_BYTES // 2
    font_count = WORKER_CHILD_MEMORY_LIMIT_BYTES // map_bytes + 1
    path = tmp_path / "fonts.pdf"
    path.write_bytes(many_fonts_pdf(font_count, map_bytes))

    result = subprocess.run(  # noqa: S603 -- this interpreter, on the test's own script
        [sys.executable, "-c", _EXTRACT_IN_A_NEW_CHILD, str(path)],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.stdout.splitlines()[-1:] == ["pdf_unreadable"], result.stderr
