import codecs
import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import BinaryIO, Final

from app.core.exceptions import (
    PayloadTooLargeError,
    UnprocessableContentError,
    UnsupportedMediaTypeError,
)
from app.models.document import ORIGINAL_FILENAME_MAX_LENGTH, DocumentContentType

ALLOWED_EXTENSIONS: Final[Mapping[str, DocumentContentType]] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
}
FALLBACK_FILENAME_STEM: Final = "document"
PDF_SIGNATURE: Final = b"%PDF-"
# PDF readers accept a header that follows up to 1 KiB of other bytes.
PDF_SIGNATURE_WINDOW_BYTES: Final = 1024
UPLOAD_CHUNK_BYTES: Final = 64 * 1024
# Control characters, plus format characters: bidi overrides and zero-width characters
# can make "notes<U+202E>fdp.txt" display as "notestxt.pdf".
_STRIPPED_CATEGORIES: Final = frozenset({"Cc", "Cf"})

_UNSUPPORTED_FILE_TYPE_MESSAGE: Final = (
    "Only PDF, Markdown (.md) and plain text (.txt) files can be uploaded."
)
_NOT_A_PDF_MESSAGE: Final = "The file is not a PDF document."
_INVALID_TEXT_ENCODING_MESSAGE: Final = "Markdown and text files must be encoded in UTF-8."
_EMPTY_FILE_MESSAGE: Final = "The file is empty."
_FILE_TOO_LARGE_MESSAGE: Final = "The file is larger than the upload limit."


@dataclass(frozen=True, slots=True)
class InspectedUpload:
    """An upload that passed every check, read to its end."""

    size_bytes: int
    sha256: str


def _split_extension(name: str) -> tuple[str, str]:
    stem, dot, suffix = name.rpartition(".")
    if not dot or not suffix:
        return name, ""
    return stem, dot + suffix


def _content_type_of(extension: str) -> DocumentContentType:
    content_type = ALLOWED_EXTENSIONS.get(extension.lower())
    if content_type is None:
        raise UnsupportedMediaTypeError(
            _UNSUPPORTED_FILE_TYPE_MESSAGE, code="unsupported_file_type"
        )
    return content_type


def extension_for(filename: str) -> str:
    """The lower-case extension of an uploadable file name; any other name is a 415."""
    extension = _split_extension(filename)[1].lower()
    _content_type_of(extension)
    return extension


def content_type_for(filename: str) -> DocumentContentType:
    """The content type of an uploadable file name; any other name is a 415."""
    return _content_type_of(_split_extension(filename)[1])


def sanitize_filename(raw: str) -> str:
    """Turn a client-supplied file name into a display name; it never becomes a path."""
    name = raw.replace("\\", "/").rpartition("/")[2]
    name = "".join(char for char in name if unicodedata.category(char) not in _STRIPPED_CATEGORIES)
    name = unicodedata.normalize("NFC", " ".join(name.split()))
    stem, extension = _split_extension(name)
    stem = stem or FALLBACK_FILENAME_STEM
    kept_stem_length = max(ORIGINAL_FILENAME_MAX_LENGTH - len(extension), 0)
    return (stem[:kept_stem_length] + extension)[:ORIGINAL_FILENAME_MAX_LENGTH]


def _not_a_pdf() -> UnsupportedMediaTypeError:
    return UnsupportedMediaTypeError(_NOT_A_PDF_MESSAGE, code="unsupported_file_type")


def _invalid_text_encoding() -> UnprocessableContentError:
    return UnprocessableContentError(_INVALID_TEXT_ENCODING_MESSAGE, code="invalid_text_encoding")


class UploadInspector:
    """Checks an upload chunk by chunk while it is copied, so the file is read only once."""

    def __init__(self, extension: str) -> None:
        self._is_pdf = _content_type_of(extension) == "application/pdf"
        self._sha256 = hashlib.sha256()
        self._size = 0
        self._pdf_head = b""
        self._pdf_signature_seen = False
        self._utf8 = codecs.getincrementaldecoder("utf-8")()

    def feed(self, chunk: bytes) -> None:
        self._sha256.update(chunk)
        self._size += len(chunk)
        if self._is_pdf:
            self._look_for_pdf_signature(chunk)
        else:
            self._check_text(chunk, final=False)

    def finish(self) -> InspectedUpload:
        if self._size == 0:
            raise UnprocessableContentError(_EMPTY_FILE_MESSAGE, code="empty_file")
        if not self._is_pdf:
            # A multi-byte character cut off at the end of the file shows up only here.
            self._check_text(b"", final=True)
        elif not self._pdf_signature_seen:
            raise _not_a_pdf()
        return InspectedUpload(size_bytes=self._size, sha256=self._sha256.hexdigest())

    def _look_for_pdf_signature(self, chunk: bytes) -> None:
        if self._pdf_signature_seen:
            return
        self._pdf_head += chunk[: PDF_SIGNATURE_WINDOW_BYTES - len(self._pdf_head)]
        if PDF_SIGNATURE in self._pdf_head:
            self._pdf_signature_seen = True
        elif len(self._pdf_head) == PDF_SIGNATURE_WINDOW_BYTES:
            raise _not_a_pdf()

    def _check_text(self, chunk: bytes, *, final: bool) -> None:
        # UTF-16 and UTF-32 byte order marks are invalid UTF-8 or contain NUL bytes,
        # so these two checks reject such files as well.
        if b"\x00" in chunk:
            raise _invalid_text_encoding()
        try:
            self._utf8.decode(chunk, final)
        except UnicodeDecodeError as exc:
            raise _invalid_text_encoding() from exc


def copy_upload(
    source: BinaryIO,
    destination: BinaryIO,
    inspector: UploadInspector,
    *,
    max_bytes: int,
    chunk_size: int = UPLOAD_CHUNK_BYTES,
) -> InspectedUpload:
    """Copy an upload through the inspector; nothing past max_bytes is written."""
    copied = 0
    while chunk := source.read(chunk_size):
        copied += len(chunk)
        if copied > max_bytes:
            raise PayloadTooLargeError(_FILE_TOO_LARGE_MESSAGE, code="payload_too_large")
        inspector.feed(chunk)
        destination.write(chunk)
    return inspector.finish()
