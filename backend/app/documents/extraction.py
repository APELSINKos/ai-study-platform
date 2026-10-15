"""Text extraction from stored PDF, Markdown and plain-text files."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pypdf
import structlog
from celery.exceptions import SoftTimeLimitExceeded
from pypdf import PageObject, PasswordType, PdfReader
from pypdf.generic import DictionaryObject, StreamObject

from app.core.config import MIB
from app.documents.errors import (
    TEXT_TOO_LONG_MESSAGE,
    DocumentProcessingError,
    ProcessingDeadlineExceeded,
)
from app.models.document import DocumentContentType

logger = structlog.get_logger(__name__)

# A file of a few kilobytes can inflate to gigabytes, and text extraction parses a page's
# whole content stream in Python (seconds per mebibyte), so both are capped well below
# what pypdf allows by default (75 MB per stream). The content of the form XObjects a page
# draws counts as the page's: pypdf parses it again each time the form is drawn.
MAX_PDF_STREAM_BYTES: Final = 8 * MIB
MAX_PDF_PAGE_CONTENT_BYTES: Final = 2 * MIB
MAX_PDF_DOCUMENT_CONTENT_BYTES: Final = 32 * MIB
# pypdf skips the forms a page draws after this many draws (5,000 by default). Text is
# rarely in more than a few forms; a chart may draw a small one at each of its points.
MAX_PDF_FORMS_PER_PAGE: Final = 500
# Every per-stream output limit pypdf has, one per compression filter.
_STREAM_OUTPUT_LIMITS: Final = dict.fromkeys(
    (
        "array_based_stream_maximum_output_length",
        "brotli_maximum_output_length",
        "jbig2_maximum_output_length",
        "lzw_maximum_output_length",
        "run_length_maximum_output_length",
        "zlib_maximum_output_length",
    ),
    MAX_PDF_STREAM_BYTES,
)

_PDF_UNREADABLE_MESSAGE: Final = "The PDF file could not be read."
_PDF_ENCRYPTED_MESSAGE: Final = "The PDF file is protected by a password."
_TOO_MANY_PAGES_MESSAGE: Final = "The PDF file has more pages than can be processed."
_TOO_MUCH_PAGE_CONTENT_MESSAGE: Final = "The PDF file has more page content than can be processed."


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """A document's text: page by page for a PDF, whole for Markdown and plain text."""

    pages: list[str] | None
    text: str | None
    page_count: int | None


def extract(
    path: Path,
    content_type: DocumentContentType,
    *,
    max_pdf_pages: int,
    max_chars: int,
    check_deadline: Callable[[], None],
) -> ExtractedDocument:
    """Read a stored file's text, checking the deadline before each PDF page.

    A file that cannot be processed raises DocumentProcessingError with the code to record;
    ProcessingDeadlineExceeded and Celery's SoftTimeLimitExceeded always pass through.
    """
    if content_type == "application/pdf":
        pages = _extract_pdf(
            path, max_pages=max_pdf_pages, max_chars=max_chars, check_deadline=check_deadline
        )
        return ExtractedDocument(pages=pages, text=None, page_count=len(pages))
    # The upload checks proved the file is UTF-8; "utf-8-sig" drops a byte order mark.
    text = path.read_bytes().decode("utf-8-sig")
    if len(text) > max_chars:
        raise DocumentProcessingError("text_too_long", TEXT_TOO_LONG_MESSAGE)
    return ExtractedDocument(pages=None, text=text, page_count=None)


def _extract_pdf(
    path: Path, *, max_pages: int, max_chars: int, check_deadline: Callable[[], None]
) -> list[str]:
    # Outside the try below: a renamed pypdf setting must fail loudly, not as a bad file.
    with (
        path.open("rb") as file,
        pypdf.apply_configuration(
            None,
            **_STREAM_OUTPUT_LIMITS,
            xform_maximum_invocations_per_extraction=MAX_PDF_FORMS_PER_PAGE,
        ),
    ):
        try:
            return _read_pages(
                PdfReader(file),
                max_pages=max_pages,
                max_chars=max_chars,
                check_deadline=check_deadline,
            )
        except (SoftTimeLimitExceeded, ProcessingDeadlineExceeded, DocumentProcessingError):
            raise
        except Exception as exc:
            # A damaged file can make pypdf fail with almost any exception, not only its own.
            logger.warning("pdf_extraction_failed", exc_info=True)
            raise DocumentProcessingError("pdf_unreadable", _PDF_UNREADABLE_MESSAGE) from exc


def _read_pages(
    reader: PdfReader, *, max_pages: int, max_chars: int, check_deadline: Callable[[], None]
) -> list[str]:
    # A file with only an owner password opens with an empty one, as in any viewer.
    if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        raise DocumentProcessingError("pdf_encrypted", _PDF_ENCRYPTED_MESSAGE)
    if len(reader.pages) > max_pages:
        raise DocumentProcessingError("too_many_pages", _TOO_MANY_PAGES_MESSAGE)
    limits = _ContentLimits(check_deadline)
    texts: list[str] = []
    chars = 0
    for page in reader.pages:
        check_deadline()
        limits.start_page(page)
        text = page.extract_text(
            visitor_operand_before=limits.before_operator,
            visitor_operand_after=limits.after_operator,
        )
        limits.finish_page()
        chars += len(text)
        if chars > max_chars:
            raise DocumentProcessingError("text_too_long", TEXT_TOO_LONG_MESSAGE)
        texts.append(text)
    return texts


class _ContentLimits:
    """Keeps the content pypdf parses within the limits and checks the deadline as it goes.

    pypdf calls the operator hooks for every operator of a page and of the forms it draws.
    A form is counted before pypdf parses it, by the same rules pypdf uses to decide whether
    it parses it at all. pypdf swallows any exception raised while it reads a form, so the
    first one raised in a hook is raised again on every later operator and when the page
    is done.
    """

    def __init__(self, check_deadline: Callable[[], None]) -> None:
        self._check_deadline = check_deadline
        self._document_bytes = 0
        self._page_bytes = 0
        self._forms_left = 0
        # The page and the forms pypdf is reading, the innermost last.
        self._reading: list[DictionaryObject] = []
        self._error: Exception | None = None

    def start_page(self, page: PageObject) -> None:
        self._page_bytes = 0
        self._forms_left = pypdf.get_configuration().xform_maximum_invocations_per_extraction
        self._reading = [page]
        self._error = None
        self._count(_content_bytes(page))

    def before_operator(self, operator: bytes, operands: list[Any], _cm: Any, _tm: Any) -> None:
        if self._error is not None:
            raise self._error
        try:
            self._check_deadline()
            if operator == b"Do" and operands:
                self._reading.append(self._draw(operands[0]))
        except Exception as error:
            self._error = error
            raise

    def after_operator(self, operator: bytes, operands: list[Any], _cm: Any, _tm: Any) -> None:
        if operator == b"Do" and operands:
            self._reading.pop()

    def finish_page(self) -> None:
        if self._error is not None:
            raise self._error

    def _draw(self, name: object) -> DictionaryObject:
        """Count the form a Do operator draws if pypdf parses it; return what pypdf reads next.

        pypdf skips anything but a form, a form it is already inside and every form past its
        number per page; after a skipped draw it reads on in the same content, which is
        pushed again for after_operator to pop. It parses nothing for a form without
        resources or without a stream.
        """
        current = self._reading[-1]
        form = _drawn_form(_resources(current), name)
        if form is None or self._forms_left == 0 or any(form is item for item in self._reading):
            return current
        self._forms_left -= 1
        if isinstance(form, StreamObject) and _resources(form):
            self._count(len(form.get_data()))
        return form

    def _count(self, content_bytes: int) -> None:
        self._page_bytes += content_bytes
        self._document_bytes += content_bytes
        if (
            self._page_bytes > MAX_PDF_PAGE_CONTENT_BYTES
            or self._document_bytes > MAX_PDF_DOCUMENT_CONTENT_BYTES
        ):
            raise DocumentProcessingError("pdf_unreadable", _TOO_MUCH_PAGE_CONTENT_MESSAGE)


def _content_bytes(page: PageObject) -> int:
    """The decoded size of the page's own content stream."""
    contents = page.get_contents()
    return 0 if contents is None else len(contents.get_data())


def _resources(content: DictionaryObject) -> DictionaryObject:
    """A page's or a form's resources as pypdf finds them: inherited, empty if malformed."""
    resources = content.get_inherited("/Resources", DictionaryObject())
    return resources if isinstance(resources, DictionaryObject) else DictionaryObject()


def _drawn_form(resources: DictionaryObject, name: object) -> DictionaryObject | None:
    """The form XObject named by a Do operator, looked up as pypdf does; None for others."""
    xobjects = _entry(resources, "/XObject")
    if not isinstance(xobjects, DictionaryObject) or not isinstance(name, str):
        return None
    drawn = _entry(xobjects, name)
    # pypdf reads anything with a subtype other than an image as a form.
    if not isinstance(drawn, DictionaryObject) or _entry(drawn, "/Subtype") in (None, "/Image"):
        return None
    return drawn


def _entry(dictionary: DictionaryObject, key: str) -> object:
    """dictionary[key] with an indirect reference followed, None if the key is missing."""
    # Unlike indexing, get() returns an indirect reference as it is.
    value = dictionary.get(key)
    return None if value is None else value.get_object()
