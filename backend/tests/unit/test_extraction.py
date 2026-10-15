# ruff: noqa: RUF001 -- Russian sample text is intended

import dataclasses
import io
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pypdf
import pytest
from celery.exceptions import SoftTimeLimitExceeded
from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.errors import DependencyError

from app.core.config import MIB
from app.core.logging import configure_logging
from app.documents import extraction
from app.documents.errors import DocumentProcessingError, ProcessingDeadlineExceeded
from app.documents.extraction import (
    MAX_PDF_PAGE_CONTENT_BYTES,
    MAX_PDF_STREAM_BYTES,
    ExtractedDocument,
    extract,
)
from app.models.document import DocumentContentType
from tests.fixtures.pdf_builder import broken_pdf, empty_pdf, inflating_pdf, text_pdf

LECTURE_PDF: Final = Path(__file__).resolve().parents[1] / "fixtures" / "lecture-ru.pdf"
MAX_PDF_PAGES: Final = 500
MAX_CHARS: Final = 2_000_000
BOMB_MAX_FILE_BYTES: Final = 25 * 1024
BOMB_TIME_LIMIT_SECONDS: Final = 2.0


def _no_deadline() -> None:
    return None


class _Deadline:
    """A deadline check that counts its calls and fails from the given call on."""

    def __init__(
        self,
        *,
        fails_at_check: int | None = None,
        error: type[Exception] = ProcessingDeadlineExceeded,
    ) -> None:
        self.checks = 0
        self._fails_at_check = fails_at_check
        self._error = error

    def __call__(self) -> None:
        self.checks += 1
        if self._fails_at_check is not None and self.checks >= self._fails_at_check:
            raise self._error()


def _extract(
    path: Path,
    content_type: DocumentContentType,
    *,
    max_pdf_pages: int = MAX_PDF_PAGES,
    max_chars: int = MAX_CHARS,
    check_deadline: Callable[[], None] = _no_deadline,
) -> ExtractedDocument:
    return extract(
        path,
        content_type,
        max_pdf_pages=max_pdf_pages,
        max_chars=max_chars,
        check_deadline=check_deadline,
    )


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _encrypted(pdf: bytes, *, user_password: str) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    writer.encrypt(user_password=user_password, owner_password="owner", algorithm="AES-256")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("content_type", ["text/markdown", "text/plain"])
def test_text_files_are_decoded_as_utf8_without_the_byte_order_mark(
    tmp_path: Path, content_type: DocumentContentType
) -> None:
    path = _write(tmp_path, "notes", "\ufeff# Конспект\r\n\nНормальные формы.\n".encode())

    extracted = _extract(path, content_type)

    assert extracted == ExtractedDocument(
        pages=None, text="# Конспект\r\n\nНормальные формы.\n", page_count=None
    )


def test_a_text_file_at_the_character_limit_is_accepted(tmp_path: Path) -> None:
    # Ten characters, twenty bytes: the limit counts characters.
    path = _write(tmp_path, "notes.txt", "Нормализац".encode())

    assert _extract(path, "text/plain", max_chars=10).text == "Нормализац"


def test_a_text_file_over_the_character_limit_is_too_long(tmp_path: Path) -> None:
    path = _write(tmp_path, "notes.md", b"0123456789A")

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "text/markdown", max_chars=10)

    assert caught.value.code == "text_too_long"


def test_each_pdf_page_is_extracted_on_its_own(tmp_path: Path) -> None:
    pdf = text_pdf([["Normal forms", "The first page."], ["The second page."], ["The third."]])
    path = _write(tmp_path, "lecture.pdf", pdf)

    extracted = _extract(path, "application/pdf")

    assert extracted.text is None
    assert extracted.page_count == 3
    assert extracted.pages is not None
    assert [page.strip() for page in extracted.pages] == [
        "Normal forms\nThe first page.",
        "The second page.",
        "The third.",
    ]


def test_pdf_pages_without_content_extract_as_empty_text(tmp_path: Path) -> None:
    path = _write(tmp_path, "blank.pdf", empty_pdf(page_count=2))

    assert _extract(path, "application/pdf") == ExtractedDocument(
        pages=["", ""], text=None, page_count=2
    )


def test_a_russian_pdf_printed_by_a_browser_is_extracted_page_by_page() -> None:
    extracted = _extract(LECTURE_PDF, "application/pdf")

    assert extracted.text is None
    assert extracted.pages is not None
    assert extracted.page_count == len(extracted.pages) >= 4
    assert extracted.pages[0].startswith("Лекция 4. Нормализация реляционных баз данных\n")
    for number, page in enumerate(extracted.pages, start=1):
        assert "Базы данных — конспект лекций" in page
        assert page.rstrip().endswith(f"Стр. {number}")


def test_a_pdf_that_needs_a_password_is_encrypted(tmp_path: Path) -> None:
    pdf = _encrypted(text_pdf([["Private notes."]]), user_password="secret")
    path = _write(tmp_path, "locked.pdf", pdf)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_encrypted"


def test_a_pdf_restricted_only_by_an_owner_password_is_read(tmp_path: Path) -> None:
    # Such a file opens without a password; the owner password only limits editing.
    pdf = _encrypted(text_pdf([["Shared notes."]]), user_password="")
    path = _write(tmp_path, "restricted.pdf", pdf)

    pages = _extract(path, "application/pdf").pages

    assert pages is not None
    assert [page.strip() for page in pages] == ["Shared notes."]


def test_a_pdf_with_too_many_pages_is_rejected_before_any_page_is_read(tmp_path: Path) -> None:
    path = _write(tmp_path, "book.pdf", text_pdf([["One."], ["Two."], ["Three."]]))
    deadline = _Deadline()

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf", max_pdf_pages=2, check_deadline=deadline)

    assert caught.value.code == "too_many_pages"
    assert deadline.checks == 0


def test_a_pdf_with_the_maximum_number_of_pages_is_read(tmp_path: Path) -> None:
    path = _write(tmp_path, "book.pdf", text_pdf([["One."], ["Two."]]))

    assert _extract(path, "application/pdf", max_pdf_pages=2).page_count == 2


def test_pdf_text_over_the_character_limit_stops_extraction_early(tmp_path: Path) -> None:
    line = "x" * 50
    path = _write(tmp_path, "long.pdf", text_pdf([[line], [line], [line]]))
    deadline = _Deadline()

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf", max_chars=80, check_deadline=deadline)

    assert caught.value.code == "text_too_long"
    # The second page went over the limit, so the third was never started.
    assert deadline.checks == 2


def test_the_deadline_is_checked_before_each_pdf_page(tmp_path: Path) -> None:
    path = _write(tmp_path, "slow.pdf", text_pdf([["One."], ["Two."], ["Three."]]))
    deadline = _Deadline()

    _extract(path, "application/pdf", check_deadline=deadline)

    assert deadline.checks == 3


def test_a_passed_deadline_stops_extraction_between_pages(tmp_path: Path) -> None:
    path = _write(tmp_path, "slow.pdf", text_pdf([["One."], ["Two."], ["Three."]]))
    deadline = _Deadline(fails_at_check=2)

    with pytest.raises(ProcessingDeadlineExceeded):
        _extract(path, "application/pdf", check_deadline=deadline)

    assert deadline.checks == 2


def _failing_extract_text(error: Exception) -> Callable[..., str]:
    def extract_text(self: PageObject, *args: Any, **kwargs: Any) -> str:
        raise error

    return extract_text


def _json_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


@pytest.mark.parametrize(
    "pdf",
    [broken_pdf(), text_pdf([["Cut short."]])[:200], b"%PDF-1.7\n"],
    ids=["garbage", "truncated", "signature-only"],
)
def test_a_file_that_is_not_a_readable_pdf_is_unreadable(tmp_path: Path, pdf: bytes) -> None:
    path = _write(tmp_path, "broken.pdf", pdf)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_unreadable"


@pytest.mark.parametrize(
    "error",
    [ValueError("unexpected"), DependencyError("cryptography is required")],
    ids=["unexpected-error", "missing-dependency"],
)
def test_any_failure_inside_the_pdf_library_makes_the_pdf_unreadable_and_is_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    configure_logging("INFO", "json")
    path = _write(tmp_path, "odd.pdf", text_pdf([["Fine on the surface."]]))
    monkeypatch.setattr(PageObject, "extract_text", _failing_extract_text(error))

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_unreadable"
    assert caught.value.__cause__ is error
    [line] = [
        line
        for line in _json_lines(capsys.readouterr().out)
        if line["event"] == "pdf_extraction_failed"
    ]
    assert line["level"] == "warning"
    assert "exception" in line


@pytest.mark.parametrize(
    "error", [SoftTimeLimitExceeded(), ProcessingDeadlineExceeded()], ids=["soft-limit", "deadline"]
)
def test_a_time_limit_inside_the_pdf_library_is_not_mistaken_for_an_unreadable_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    path = _write(tmp_path, "slow.pdf", text_pdf([["Slow."]]))
    monkeypatch.setattr(PageObject, "extract_text", _failing_extract_text(error))

    with pytest.raises(type(error)):
        _extract(path, "application/pdf")


@pytest.mark.parametrize("error", [SoftTimeLimitExceeded, ProcessingDeadlineExceeded])
def test_a_time_limit_from_the_deadline_check_is_not_mistaken_for_an_unreadable_pdf(
    tmp_path: Path, error: type[Exception]
) -> None:
    path = _write(tmp_path, "slow.pdf", text_pdf([["Slow."]]))

    with pytest.raises(error):
        _extract(path, "application/pdf", check_deadline=_Deadline(fails_at_check=1, error=error))


def test_a_missing_file_is_not_mistaken_for_an_unreadable_pdf(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _extract(tmp_path / "gone.pdf", "application/pdf")


def _content_bytes(pdf: bytes) -> int:
    contents = PdfReader(io.BytesIO(pdf)).pages[0].get_contents()
    assert contents is not None
    return len(contents.get_data())


def test_a_small_pdf_that_inflates_to_sixteen_mebibytes_is_stopped_quickly(
    tmp_path: Path,
) -> None:
    pdf = inflating_pdf(16 * MIB)
    assert len(pdf) < BOMB_MAX_FILE_BYTES
    path = _write(tmp_path, "bomb.pdf", pdf)

    started = time.perf_counter()
    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert time.perf_counter() - started < BOMB_TIME_LIMIT_SECONDS
    assert caught.value.code == "pdf_unreadable"


def test_a_page_with_more_content_than_allowed_is_unreadable(tmp_path: Path) -> None:
    # Under the stream limit, so only the page check can stop it.
    pdf = inflating_pdf(MAX_PDF_PAGE_CONTENT_BYTES + 1)
    assert MAX_PDF_PAGE_CONTENT_BYTES + 1 < MAX_PDF_STREAM_BYTES
    path = _write(tmp_path, "heavy.pdf", pdf)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_unreadable"


def test_page_content_exactly_at_the_page_limit_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = text_pdf([["A page of ordinary size."]])
    monkeypatch.setattr(extraction, "MAX_PDF_PAGE_CONTENT_BYTES", _content_bytes(pdf))
    path = _write(tmp_path, "notes.pdf", pdf)

    assert _extract(path, "application/pdf").page_count == 1


def test_page_content_is_limited_for_the_whole_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = "The same amount of content on every page."
    pdf = text_pdf([[line], [line], [line]])
    monkeypatch.setattr(extraction, "MAX_PDF_DOCUMENT_CONTENT_BYTES", 2 * _content_bytes(pdf))
    path = _write(tmp_path, "notes.pdf", pdf)
    deadline = _Deadline()

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf", check_deadline=deadline)

    assert caught.value.code == "pdf_unreadable"
    assert deadline.checks == 3


def test_page_content_exactly_at_the_document_limit_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = "The same amount of content on every page."
    pdf = text_pdf([[line], [line], [line]])
    monkeypatch.setattr(extraction, "MAX_PDF_DOCUMENT_CONTENT_BYTES", 3 * _content_bytes(pdf))
    path = _write(tmp_path, "notes.pdf", pdf)

    assert _extract(path, "application/pdf").page_count == 3


def test_every_stream_output_limit_of_the_pdf_library_is_lowered_while_extracting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[pypdf.Configuration] = []

    def extract_text(self: PageObject, *args: Any, **kwargs: Any) -> str:
        seen.append(pypdf.get_configuration())
        return ""

    monkeypatch.setattr(PageObject, "extract_text", extract_text)
    path = _write(tmp_path, "notes.pdf", text_pdf([["Configured."]]))

    _extract(path, "application/pdf")

    [configuration] = seen
    output_limits = {
        field.name: getattr(configuration, field.name)
        for field in dataclasses.fields(configuration)
        if field.name.endswith("_maximum_output_length")
    }
    assert len(output_limits) >= 6
    assert set(output_limits.values()) == {MAX_PDF_STREAM_BYTES}
    assert pypdf.get_configuration() == pypdf.Configuration()
