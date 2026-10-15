"""Text extraction from stored PDF, Markdown and plain-text files."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pypdf
import structlog
from celery.exceptions import SoftTimeLimitExceeded
from pypdf import PageObject, PasswordType, PdfReader

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
# what pypdf allows by default (75 MB per stream).
MAX_PDF_STREAM_BYTES: Final = 8 * MIB
MAX_PDF_PAGE_CONTENT_BYTES: Final = 2 * MIB
MAX_PDF_DOCUMENT_CONTENT_BYTES: Final = 32 * MIB
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
    with path.open("rb") as file, pypdf.apply_configuration(None, **_STREAM_OUTPUT_LIMITS):
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
    texts: list[str] = []
    content_bytes = 0
    chars = 0
    for page in reader.pages:
        check_deadline()
        page_bytes = _content_bytes(page)
        content_bytes += page_bytes
        if (
            page_bytes > MAX_PDF_PAGE_CONTENT_BYTES
            or content_bytes > MAX_PDF_DOCUMENT_CONTENT_BYTES
        ):
            raise DocumentProcessingError("pdf_unreadable", _TOO_MUCH_PAGE_CONTENT_MESSAGE)
        text = page.extract_text()
        chars += len(text)
        if chars > max_chars:
            raise DocumentProcessingError("text_too_long", TEXT_TOO_LONG_MESSAGE)
        texts.append(text)
    return texts


def _content_bytes(page: PageObject) -> int:
    """The decoded size of the content stream that extracting the page's text parses."""
    contents = page.get_contents()
    return 0 if contents is None else len(contents.get_data())
