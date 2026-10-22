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
from pypdf.errors import DependencyError, LimitReachedError

from app.core.config import MIB
from app.core.logging import configure_logging
from app.documents import extraction
from app.documents.errors import DocumentProcessingError, ProcessingDeadlineExceeded
from app.documents.extraction import (
    MAX_PDF_FORMS_PER_PAGE,
    MAX_PDF_PAGE_CONTENT_BYTES,
    MAX_PDF_STREAM_BYTES,
    ExtractedDocument,
    extract,
)
from app.models.document import DocumentContentType
from tests.fixtures.pdf_builder import (
    Form,
    Image,
    broken_pdf,
    empty_pdf,
    filler,
    form_pdf,
    inflating_pdf,
    text_pdf,
)

LECTURE_PDF: Final = Path(__file__).resolve().parents[1] / "fixtures" / "lecture-ru.pdf"
MAX_PDF_PAGES: Final = 500
MAX_CHARS: Final = 2_000_000
BOMB_MAX_FILE_BYTES: Final = 25 * 1024
# Timed with coverage's tracer paused (no_cover): tracing multiplies the time of every step.
BOMB_TIME_LIMIT_SECONDS: Final = 2.0
FORM_BYTES: Final = 1000


def _no_deadline() -> None:
    return None


class _Deadline:
    """A deadline check that counts its calls and fails from the given call on."""

    def __init__(
        self,
        *,
        fails_at_check: int | None = None,
        error: type[BaseException] = ProcessingDeadlineExceeded,
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


def _record_pages_read(monkeypatch: pytest.MonkeyPatch) -> list[PageObject]:
    """Every page whose text extraction starts from now on, in order."""
    pages: list[PageObject] = []
    extract_text = PageObject.extract_text

    def recording_extract_text(self: PageObject, *args: Any, **kwargs: Any) -> str:
        pages.append(self)
        return extract_text(self, *args, **kwargs)

    monkeypatch.setattr(PageObject, "extract_text", recording_extract_text)
    return pages


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


def test_pdf_text_over_the_character_limit_stops_extraction_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = "x" * 50
    path = _write(tmp_path, "long.pdf", text_pdf([[line], [line], [line]]))
    pages_read = _record_pages_read(monkeypatch)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf", max_chars=80)

    assert caught.value.code == "text_too_long"
    # The second page went over the limit, so the third was never started.
    assert len(pages_read) == 2


def test_the_deadline_is_checked_before_each_pdf_page(tmp_path: Path) -> None:
    # Pages without content have no operators to check the deadline before.
    path = _write(tmp_path, "blank.pdf", empty_pdf(page_count=3))
    deadline = _Deadline()

    _extract(path, "application/pdf", check_deadline=deadline)

    assert deadline.checks == 3


def test_the_deadline_is_also_checked_before_each_operator_of_a_page(tmp_path: Path) -> None:
    pdf = text_pdf([["One."]])
    path = _write(tmp_path, "notes.pdf", pdf)
    contents = PdfReader(io.BytesIO(pdf)).pages[0].get_contents()
    assert contents is not None
    deadline = _Deadline()

    _extract(path, "application/pdf", check_deadline=deadline)

    assert deadline.checks == 1 + len(contents.operations)


def test_a_passed_deadline_stops_extraction_between_pages(tmp_path: Path) -> None:
    path = _write(tmp_path, "blank.pdf", empty_pdf(page_count=3))
    deadline = _Deadline(fails_at_check=2)

    with pytest.raises(ProcessingDeadlineExceeded):
        _extract(path, "application/pdf", check_deadline=deadline)

    assert deadline.checks == 2


def test_a_passed_deadline_stops_a_page_that_draws_a_form_again_and_again(
    tmp_path: Path,
) -> None:
    # pypdf parses the form's content once per draw: a page of a few bytes takes seconds.
    pdf = form_pdf([b"/X0 Do\n" * 4], {"X0": Form(filler(MAX_PDF_PAGE_CONTENT_BYTES // 8))})
    path = _write(tmp_path, "forms.pdf", pdf)
    deadline = _Deadline(fails_at_check=2)

    with pytest.raises(ProcessingDeadlineExceeded):
        _extract(path, "application/pdf", check_deadline=deadline)

    # The page itself, then the first operator, before the first form was drawn.
    assert deadline.checks == 2


def test_a_deadline_passed_inside_a_form_still_stops_extraction(tmp_path: Path) -> None:
    # pypdf swallows any exception raised while it reads a form and goes on with the page.
    pdf = form_pdf([b"/X0 Do"], {"X0": Form(b"q Q\n" * 3)})
    path = _write(tmp_path, "form.pdf", pdf)
    # The page itself, the operator that draws the form and then the form's first operator.
    deadline = _Deadline(fails_at_check=3)

    with pytest.raises(ProcessingDeadlineExceeded):
        _extract(path, "application/pdf", check_deadline=deadline)

    assert deadline.checks == 3


def _failing_extract_text(error: BaseException) -> Callable[..., str]:
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    path = _write(tmp_path, "slow.pdf", text_pdf([["Slow."]]))
    monkeypatch.setattr(PageObject, "extract_text", _failing_extract_text(error))

    with pytest.raises(type(error)):
        _extract(path, "application/pdf")


@pytest.mark.parametrize("error", [SoftTimeLimitExceeded, ProcessingDeadlineExceeded])
def test_a_time_limit_from_the_deadline_check_is_not_mistaken_for_an_unreadable_pdf(
    tmp_path: Path, error: type[BaseException]
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


@pytest.mark.no_cover
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
    # Stopped by the stream limit while inflating, not by the page check afterwards.
    assert isinstance(caught.value.__cause__, LimitReachedError)


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
    pages_read = _record_pages_read(monkeypatch)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_unreadable"
    # The third page went over the limit before its text was extracted.
    assert len(pages_read) == 2


def test_page_content_exactly_at_the_document_limit_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = "The same amount of content on every page."
    pdf = text_pdf([[line], [line], [line]])
    monkeypatch.setattr(extraction, "MAX_PDF_DOCUMENT_CONTENT_BYTES", 3 * _content_bytes(pdf))
    path = _write(tmp_path, "notes.pdf", pdf)

    assert _extract(path, "application/pdf").page_count == 3


def _drawing_pdf(draws: int, form: Form | None = None) -> bytes:
    """One page that draws the form X0 draws times."""
    return form_pdf([b"/X0 Do\n" * draws], {"X0": form or Form(filler(FORM_BYTES))})


def _allow_page_bytes(monkeypatch: pytest.MonkeyPatch, pdf: bytes, form_bytes: int) -> None:
    """Set the page limit to the first page's own content plus form_bytes."""
    monkeypatch.setattr(extraction, "MAX_PDF_PAGE_CONTENT_BYTES", _content_bytes(pdf) + form_bytes)


def test_text_a_page_draws_through_a_form_is_extracted(tmp_path: Path) -> None:
    form = Form(b"BT /F1 12 Tf 72 700 Td (Drawn by a form.) Tj ET")
    path = _write(tmp_path, "form.pdf", _drawing_pdf(1, form))

    pages = _extract(path, "application/pdf").pages

    assert pages is not None
    assert [page.strip() for page in pages] == ["Drawn by a form."]


def test_every_draw_of_a_form_counts_against_the_page_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _drawing_pdf(3)
    _allow_page_bytes(monkeypatch, pdf, 2 * FORM_BYTES)
    path = _write(tmp_path, "forms.pdf", pdf)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_unreadable"


def test_forms_drawn_up_to_the_page_limit_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = _drawing_pdf(3)
    _allow_page_bytes(monkeypatch, pdf, 3 * FORM_BYTES)
    path = _write(tmp_path, "forms.pdf", pdf)

    assert _extract(path, "application/pdf").page_count == 1


@pytest.mark.no_cover
def test_a_small_page_drawing_a_big_form_again_and_again_is_stopped_quickly(
    tmp_path: Path,
) -> None:
    # The form alone is as big as a page may be, so it is refused before it is parsed.
    pdf = _drawing_pdf(5, Form(filler(MAX_PDF_PAGE_CONTENT_BYTES)))
    assert len(pdf) < BOMB_MAX_FILE_BYTES
    path = _write(tmp_path, "forms.pdf", pdf)

    started = time.perf_counter()
    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert time.perf_counter() - started < BOMB_TIME_LIMIT_SECONDS
    assert caught.value.code == "pdf_unreadable"


def test_forms_drawn_by_a_form_count_against_the_page_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The page names only the outer form; the inner one is named by the outer form alone.
    outer = b"/Inner Do\n" * 3
    pdf = form_pdf(
        [b"/Outer Do"],
        {
            "Outer": Form(outer, draws=("Inner",)),
            "Inner": Form(filler(FORM_BYTES), named_by_page=False),
        },
    )
    _allow_page_bytes(monkeypatch, pdf, len(outer) + 2 * FORM_BYTES)
    path = _write(tmp_path, "nested.pdf", pdf)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_unreadable"


def test_forms_count_against_the_document_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = form_pdf([b"/X0 Do"] * 3, {"X0": Form(filler(FORM_BYTES))})
    page_bytes = _content_bytes(pdf) + FORM_BYTES
    monkeypatch.setattr(extraction, "MAX_PDF_DOCUMENT_CONTENT_BYTES", 3 * page_bytes - 1)
    path = _write(tmp_path, "forms.pdf", pdf)
    pages_read = _record_pages_read(monkeypatch)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_unreadable"
    assert len(pages_read) == 3


def test_a_form_drawing_itself_is_counted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pypdf does not follow a form into itself, so only the first draw is parsed.
    loop = b"/X0 Do\n" * 3
    pdf = _drawing_pdf(1, Form(loop, draws=("X0",)))
    _allow_page_bytes(monkeypatch, pdf, len(loop))
    path = _write(tmp_path, "loop.pdf", pdf)

    assert _extract(path, "application/pdf").page_count == 1


def test_forms_pypdf_skips_past_its_number_per_page_are_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pypdf skips them, so a chart that draws a small form at each of its points stays
    # within the page limit however many points it has.
    monkeypatch.setattr(extraction, "MAX_PDF_FORMS_PER_PAGE", 2)
    pdf = _drawing_pdf(5)
    _allow_page_bytes(monkeypatch, pdf, 2 * FORM_BYTES)
    path = _write(tmp_path, "chart.pdf", pdf)

    assert _extract(path, "application/pdf").page_count == 1


def test_a_form_without_resources_is_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pypdf never parses such a form for text: it cannot name a font.
    pdf = _drawing_pdf(3, Form(filler(FORM_BYTES), has_resources=False))
    _allow_page_bytes(monkeypatch, pdf, 0)
    path = _write(tmp_path, "figure.pdf", pdf)

    assert _extract(path, "application/pdf").page_count == 1


def test_images_a_page_draws_are_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = form_pdf([b"/Photo Do\n" * 3], {"Photo": Image(FORM_BYTES)})
    _allow_page_bytes(monkeypatch, pdf, 0)
    path = _write(tmp_path, "photo.pdf", pdf)

    assert _extract(path, "application/pdf").page_count == 1


def test_images_do_not_use_up_the_forms_pypdf_reads_on_a_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Otherwise images drawn first would let the forms drawn after them go uncounted.
    monkeypatch.setattr(extraction, "MAX_PDF_FORMS_PER_PAGE", 2)
    pdf = form_pdf(
        [b"/Photo Do\n" * 2 + b"/X0 Do\n"],
        {"Photo": Image(FORM_BYTES), "X0": Form(filler(FORM_BYTES))},
    )
    _allow_page_bytes(monkeypatch, pdf, FORM_BYTES - 1)
    path = _write(tmp_path, "photos.pdf", pdf)

    with pytest.raises(DocumentProcessingError) as caught:
        _extract(path, "application/pdf")

    assert caught.value.code == "pdf_unreadable"


def test_the_stream_and_form_limits_of_the_pdf_library_are_lowered_while_extracting(
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
    assert configuration.xform_maximum_invocations_per_extraction == MAX_PDF_FORMS_PER_PAGE
    assert pypdf.Configuration().xform_maximum_invocations_per_extraction > MAX_PDF_FORMS_PER_PAGE
    assert pypdf.get_configuration() == pypdf.Configuration()
