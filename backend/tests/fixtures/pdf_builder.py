"""Small PDF files written byte by byte, so tests control every page and stream."""

import zlib
from collections.abc import Sequence
from typing import Final

_HEADER: Final = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_FONT: Final = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
_PAGE: Final = (
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
    b" /Resources << /Font << /F1 3 0 R >> >>%s >>"
)
# The catalog, the page tree and the font come first; each page then takes two objects.
_FIRST_PAGE_OBJECT: Final = 4
# Saving and restoring the graphics state draws nothing, yields no text and compresses
# about a thousand to one.
_FILLER_OPERATOR: Final = b"q Q\n"


def text_pdf(pages: Sequence[Sequence[str]]) -> bytes:
    """A PDF with a page per item, each string drawn as one line of Helvetica text."""
    return _pdf([_stream(_text_operators(lines)) for lines in pages])


def empty_pdf(page_count: int = 1) -> bytes:
    """A PDF whose pages have no content stream at all."""
    return _pdf([None] * page_count)


def broken_pdf() -> bytes:
    """A PDF signature followed by bytes that are not a PDF."""
    return b"%PDF-1.7\n" + b"\x8f garbage that ends nowhere " * 20


def inflating_pdf(inflated_bytes: int) -> bytes:
    """One page whose compressed content stream inflates to exactly inflated_bytes."""
    repeats = inflated_bytes // len(_FILLER_OPERATOR) + 1
    data = (_FILLER_OPERATOR * repeats)[:inflated_bytes]
    return _pdf([_stream(zlib.compress(data, level=9), filters=b"/Filter /FlateDecode")])


def _text_operators(lines: Sequence[str]) -> bytes:
    operators = [b"BT", b"/F1 12 Tf", b"14 TL", b"72 760 Td"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        operators.append(b"(" + escaped.encode("cp1252") + b") Tj T*")
    operators.append(b"ET")
    return b"\n".join(operators)


def _stream(data: bytes, *, filters: bytes = b"") -> bytes:
    return b"<< /Length %d %s >>\nstream\n%s\nendstream" % (len(data), filters, data)


def _pdf(contents: Sequence[bytes | None]) -> bytes:
    """Assemble a PDF with one page per content stream; None leaves a page without one."""
    page_numbers = [_FIRST_PAGE_OBJECT + 2 * index for index in range(len(contents))]
    kids = b" ".join(b"%d 0 R" % number for number in page_numbers)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(contents)),
        _FONT,
    ]
    for number, content in zip(page_numbers, contents, strict=True):
        if content is None:
            objects += [_PAGE % b"", b"null"]
        else:
            objects += [_PAGE % (b" /Contents %d 0 R" % (number + 1)), content]
    return _assemble(objects)


def _assemble(objects: Sequence[bytes]) -> bytes:
    """Number the objects from 1, the catalog first, and add the cross-reference table."""
    out = bytearray(_HEADER)
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_offset = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref_offset
    return bytes(out)
