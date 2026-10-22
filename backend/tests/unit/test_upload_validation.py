import codecs
import hashlib
import io
from collections.abc import Callable
from typing import Final

import pytest

from app.core.config import MIB
from app.core.exceptions import (
    PayloadTooLargeError,
    UnprocessableContentError,
    UnsupportedMediaTypeError,
)
from app.documents.validation import (
    ALLOWED_EXTENSIONS,
    InspectedUpload,
    UploadInspector,
    content_type_for,
    copy_upload,
    extension_for,
    sanitize_filename,
)
from app.models.document import DOCUMENT_CONTENT_TYPES, ORIGINAL_FILENAME_MAX_LENGTH

PDF_HEADER: Final = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"


class _CountingReader(io.BytesIO):
    """An upload source that remembers how many bytes were read from it."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.bytes_read = 0

    def read(self, size: int | None = -1, /) -> bytes:
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


def _inspect(extension: str, *chunks: bytes) -> InspectedUpload:
    inspector = UploadInspector(extension)
    for chunk in chunks:
        inspector.feed(chunk)
    return inspector.finish()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("notes.pdf", "notes.pdf"),
        ("Лекция 3. Интегралы.pdf", "Лекция 3. Интегралы.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("..\\..\\Windows\\win.md", "win.md"),
        ("C:\\Users\\Студент\\Desktop\\Конспект.pdf", "Конспект.pdf"),
        ("lectures/week 1\\intro.md", "intro.md"),
        ("notes\u202efdp.txt", "notesfdp.txt"),
        ("lec\u200bture\u2066.md\ufeff", "lecture.md"),
        ("bad\x00na\x1fme\x7f.txt", "badname.txt"),
        ("notes\ud83d.txt", "notes.txt"),
        ("Lecture %22Intro%22.md", 'Lecture "Intro".md'),
        ("week%0D%0A1.md", "week1.md"),
        ("  my \u00a0 lecture\u2003notes  .txt ", "my lecture notes .txt"),
        ("\u0415\u0308\u043b\u043a\u0430.md", "\u0401\u043b\u043a\u0430.md"),
    ],
    ids=[
        "plain",
        "cyrillic",
        "posix-traversal",
        "windows-traversal",
        "windows-path",
        "mixed-separators",
        "bidi-override",
        "zero-width-and-isolate",
        "control-characters",
        "lone-surrogate",
        "browser-escaped-quotes",
        "browser-escaped-line-break",
        "whitespace-runs",
        "nfc",
    ],
)
def test_a_file_name_is_reduced_to_a_clean_base_name(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (".pdf", "document.pdf"),
        ("../.md", "document.md"),
        ("\u202e.txt", "document.txt"),
        ("lectures/", "document"),
        (" \u200b ", "document"),
        ("", "document"),
    ],
    ids=["extension-only", "traversal-to-extension", "invisible-stem", "folder", "blank", "empty"],
)
def test_a_name_without_a_stem_falls_back_to_document(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_a_long_name_is_cut_to_the_column_length_keeping_its_extension() -> None:
    name = sanitize_filename("я" * 300 + ".pdf")

    assert name == "я" * (ORIGINAL_FILENAME_MAX_LENGTH - len(".pdf")) + ".pdf"


def test_a_long_name_without_an_extension_is_cut_to_the_column_length() -> None:
    assert sanitize_filename("a" * 300) == "a" * ORIGINAL_FILENAME_MAX_LENGTH


def test_a_name_never_exceeds_the_column_length() -> None:
    assert len(sanitize_filename("a." + "b" * 300)) == ORIGINAL_FILENAME_MAX_LENGTH


def test_each_document_content_type_has_one_allowed_extension() -> None:
    assert set(ALLOWED_EXTENSIONS) == {".pdf", ".md", ".txt"}
    assert sorted(ALLOWED_EXTENSIONS.values()) == sorted(DOCUMENT_CONTENT_TYPES)


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("lecture.pdf", "application/pdf"),
        ("SLIDES.PDF", "application/pdf"),
        ("notes.md", "text/markdown"),
        ("Notes.Md", "text/markdown"),
        ("plain.txt", "text/plain"),
        ("backup.tar.TXT", "text/plain"),
    ],
)
def test_an_allowed_extension_gives_its_content_type_in_any_case(
    filename: str, content_type: str
) -> None:
    assert content_type_for(filename) == content_type


def test_the_extension_is_given_in_lower_case() -> None:
    assert extension_for("Lecture.PDF") == ".pdf"


def test_a_disguised_name_is_typed_by_its_real_extension() -> None:
    assert content_type_for(sanitize_filename("notes\u202efdp.txt")) == "text/plain"


@pytest.mark.parametrize("check", [content_type_for, extension_for], ids=["type", "extension"])
@pytest.mark.parametrize(
    "filename",
    ["slides.pptx", "lecture.pdf.exe", "README", "notes.", "notes.markdown", "scan.jpeg"],
)
def test_any_other_extension_is_an_unsupported_file_type(
    check: Callable[[str], object], filename: str
) -> None:
    with pytest.raises(UnsupportedMediaTypeError) as caught:
        check(filename)

    assert caught.value.code == "unsupported_file_type"


def test_the_digest_and_size_cover_every_chunk() -> None:
    data = "# Глава 1. Пределы\n".encode()

    inspected = _inspect(".md", data[:5], data[5:])

    assert inspected == InspectedUpload(
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
    )


@pytest.mark.parametrize(
    "chunks",
    [
        (PDF_HEADER + b"1 0 obj\n",),
        (b"\x00" * 1000 + PDF_HEADER,),
        (b"%PD", b"F-1.7\n"),
        (b"x" * 1019, b"%PDF-"),
    ],
    ids=["at-the-start", "after-junk", "split-across-chunks", "ending-at-byte-1024"],
)
def test_a_pdf_header_within_the_first_kibibyte_is_accepted(chunks: tuple[bytes, ...]) -> None:
    assert _inspect(".pdf", *chunks).size_bytes == len(b"".join(chunks))


def test_a_pdf_header_after_the_first_kibibyte_is_rejected_while_streaming() -> None:
    inspector = UploadInspector(".pdf")

    with pytest.raises(UnsupportedMediaTypeError) as caught:
        inspector.feed(b"x" * 1024 + PDF_HEADER)

    assert caught.value.code == "unsupported_file_type"


def test_a_short_file_without_a_pdf_header_is_rejected() -> None:
    with pytest.raises(UnsupportedMediaTypeError) as caught:
        _inspect(".pdf", b"Plain text pretending to be a PDF.")

    assert caught.value.code == "unsupported_file_type"


def test_an_upper_case_pdf_extension_is_checked_as_a_pdf() -> None:
    assert _inspect(".PDF", PDF_HEADER).size_bytes == len(PDF_HEADER)
    with pytest.raises(UnsupportedMediaTypeError):
        _inspect(".PDF", b"Plain text pretending to be a PDF.")


@pytest.mark.parametrize("extension", [".md", ".txt"])
@pytest.mark.parametrize(
    "data",
    [
        "# Конспект\n\n- предел функции\n".encode(),
        codecs.BOM_UTF8 + "Заметки".encode(),
        b"Tabs\tand\r\nWindows line ends\n",
        "Books \U0001f4da on the shelf".encode(),
    ],
    ids=["cyrillic", "utf8-bom", "tabs-and-crlf", "four-byte-character"],
)
def test_utf8_text_is_accepted(extension: str, data: bytes) -> None:
    assert _inspect(extension, data).size_bytes == len(data)


@pytest.mark.parametrize("extension", [".md", ".txt"])
@pytest.mark.parametrize(
    "data",
    [
        codecs.BOM_UTF16_LE + "notes".encode("utf-16-le"),
        codecs.BOM_UTF16_BE + "notes".encode("utf-16-be"),
        codecs.BOM_UTF32_LE + "notes".encode("utf-32-le"),
        codecs.BOM_UTF32_BE + "notes".encode("utf-32-be"),
        b"text with a \x00 byte",
        "Конспект".encode("cp1251"),
        b"overlong \xc0\xaf slash",
        b"surrogate \xed\xa0\x80 half",
        "Конспект".encode()[:-1],
    ],
    ids=[
        "utf16-le-bom",
        "utf16-be-bom",
        "utf32-le-bom",
        "utf32-be-bom",
        "nul",
        "cp1251",
        "overlong",
        "surrogate",
        "cut-off-at-the-end",
    ],
)
def test_text_that_is_not_strict_utf8_is_rejected(extension: str, data: bytes) -> None:
    with pytest.raises(UnprocessableContentError) as caught:
        _inspect(extension, data)

    assert caught.value.code == "invalid_text_encoding"


def test_a_character_split_across_chunks_is_accepted() -> None:
    data = "Привет, мир".encode()

    inspected = _inspect(".txt", *(data[index : index + 1] for index in range(len(data))))

    assert inspected.size_bytes == len(data)


def test_invalid_text_is_rejected_while_streaming() -> None:
    inspector = UploadInspector(".md")

    with pytest.raises(UnprocessableContentError) as caught:
        inspector.feed(codecs.BOM_UTF16_LE + "notes".encode("utf-16-le"))

    assert caught.value.code == "invalid_text_encoding"


@pytest.mark.parametrize("extension", [".pdf", ".md", ".txt"])
def test_an_empty_file_is_rejected(extension: str) -> None:
    with pytest.raises(UnprocessableContentError) as caught:
        _inspect(extension)

    assert caught.value.code == "empty_file"


def test_an_inspector_takes_only_an_allowed_extension() -> None:
    with pytest.raises(UnsupportedMediaTypeError) as caught:
        UploadInspector(".docx")

    assert caught.value.code == "unsupported_file_type"


def test_an_upload_is_copied_whole_and_described() -> None:
    data = PDF_HEADER + b"0" * (3 * MIB)
    destination = io.BytesIO()

    inspected = copy_upload(
        io.BytesIO(data), destination, UploadInspector(".pdf"), max_bytes=20 * MIB
    )

    assert destination.getvalue() == data
    assert inspected == InspectedUpload(
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
    )


def test_small_chunks_that_split_characters_copy_cleanly() -> None:
    data = "Глава 1. Пределы\n".encode() * 100
    destination = io.BytesIO()

    inspected = copy_upload(
        io.BytesIO(data), destination, UploadInspector(".md"), max_bytes=MIB, chunk_size=7
    )

    assert destination.getvalue() == data
    assert inspected.size_bytes == len(data)


def test_an_upload_exactly_at_the_limit_is_accepted() -> None:
    data = b"plain text notes"

    inspected = copy_upload(
        io.BytesIO(data), io.BytesIO(), UploadInspector(".txt"), max_bytes=len(data), chunk_size=3
    )

    assert inspected.size_bytes == len(data)


def test_an_upload_over_the_limit_is_rejected_before_the_excess_is_written() -> None:
    data = b"plain text notes"
    destination = io.BytesIO()

    with pytest.raises(PayloadTooLargeError) as caught:
        copy_upload(
            io.BytesIO(data),
            destination,
            UploadInspector(".txt"),
            max_bytes=len(data) - 1,
            chunk_size=4,
        )

    assert caught.value.code == "payload_too_large"
    assert destination.getvalue() == data[:12]


def test_copying_stops_reading_soon_after_the_limit() -> None:
    source = _CountingReader(b"a" * (10 * MIB))

    with pytest.raises(PayloadTooLargeError):
        copy_upload(source, io.BytesIO(), UploadInspector(".txt"), max_bytes=1024, chunk_size=256)

    assert source.bytes_read <= 1024 + 256


def test_a_file_that_is_not_a_pdf_is_rejected_without_reading_it_all() -> None:
    source = _CountingReader(b"MZ" + b"\x90" * (5 * MIB))

    with pytest.raises(UnsupportedMediaTypeError):
        copy_upload(
            source, io.BytesIO(), UploadInspector(".pdf"), max_bytes=20 * MIB, chunk_size=512
        )

    assert source.bytes_read <= 1024 + 512


def test_an_empty_upload_is_rejected() -> None:
    with pytest.raises(UnprocessableContentError) as caught:
        copy_upload(io.BytesIO(), io.BytesIO(), UploadInspector(".md"), max_bytes=MIB)

    assert caught.value.code == "empty_file"
