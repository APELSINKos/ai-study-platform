"""Small PDF files written byte by byte, so tests control every page and stream."""

import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

_HEADER: Final = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_FONT: Final = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
_PAGE: Final = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources %s%s >>"
# The catalog, the page tree and the font come first; each page then takes two objects.
_FONT_OBJECT: Final = 3
_FIRST_PAGE_OBJECT: Final = 4
# Saving and restoring the graphics state draws nothing, yields no text and compresses
# about a thousand to one.
_FILLER_OPERATOR: Final = b"q Q\n"
_FLATE_FILTER: Final = b"/Filter /FlateDecode"


@dataclass(frozen=True)
class Form:
    """A form XObject for form_pdf.

    Its resources name the font and the XObjects in draws; without resources, pypdf never
    reads a form's text. named_by_page=False leaves it out of the pages' resources, so only
    another form can draw it.
    """

    content: bytes
    draws: Sequence[str] = ()
    has_resources: bool = True
    named_by_page: bool = True


@dataclass(frozen=True)
class Image:
    """An image XObject: one row of grey pixels, size bytes once decoded."""

    size: int


def filler(size: int) -> bytes:
    """Content that draws nothing and yields no text, exactly size bytes long."""
    return (_FILLER_OPERATOR * (size // len(_FILLER_OPERATOR) + 1))[:size]


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
    data = zlib.compress(filler(inflated_bytes), level=9)
    return _pdf([_stream(data, entries=_FLATE_FILTER)])


def form_pdf(pages: Sequence[bytes], xobjects: Mapping[str, Form | Image]) -> bytes:
    """A PDF whose pages, each given as its content, draw XObjects by name: "/Chart Do".

    The pages share their resources: the font and every XObject named by the page.
    Form contents are compressed, so a form of mebibytes takes a few kilobytes.
    """
    first = _FIRST_PAGE_OBJECT + 2 * len(pages)
    numbers = {name: first + index for index, name in enumerate(xobjects)}
    page_names = [
        name
        for name, xobject in xobjects.items()
        if not isinstance(xobject, Form) or xobject.named_by_page
    ]
    return _pdf(
        [_stream(content) for content in pages],
        resources=_resources({name: numbers[name] for name in page_names}),
        more_objects=[_xobject(xobject, numbers) for xobject in xobjects.values()],
    )


def _xobject(xobject: Form | Image, numbers: Mapping[str, int]) -> bytes:
    if isinstance(xobject, Image):
        pixels = zlib.compress(b"\x00" * xobject.size, level=9)
        entries = (
            b"/Type /XObject /Subtype /Image /Width %d /Height 1"
            b" /ColorSpace /DeviceGray /BitsPerComponent 8 %s" % (xobject.size, _FLATE_FILTER)
        )
        return _stream(pixels, entries=entries)
    entries = b"/Type /XObject /Subtype /Form /BBox [0 0 612 792] " + _FLATE_FILTER
    if xobject.has_resources:
        entries += b" /Resources " + _resources({name: numbers[name] for name in xobject.draws})
    return _stream(zlib.compress(xobject.content, level=9), entries=entries)


def _resources(xobjects: Mapping[str, int]) -> bytes:
    """A resource dictionary naming the font and the given XObjects by object number."""
    named = b"".join(b" /%s %d 0 R" % (name.encode(), number) for name, number in xobjects.items())
    xobject_entry = b" /XObject <<%s >>" % named if xobjects else b""
    return b"<< /Font << /F1 %d 0 R >>%s >>" % (_FONT_OBJECT, xobject_entry)


def _text_operators(lines: Sequence[str]) -> bytes:
    operators = [b"BT", b"/F1 12 Tf", b"14 TL", b"72 760 Td"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        operators.append(b"(" + escaped.encode("cp1252") + b") Tj T*")
    operators.append(b"ET")
    return b"\n".join(operators)


def _stream(data: bytes, *, entries: bytes = b"") -> bytes:
    return b"<< /Length %d %s >>\nstream\n%s\nendstream" % (len(data), entries, data)


def _pdf(
    contents: Sequence[bytes | None],
    *,
    resources: bytes | None = None,
    more_objects: Sequence[bytes] = (),
) -> bytes:
    """Assemble a PDF with one page per content stream; None leaves a page without one.

    The objects in more_objects follow the pages, numbered on from them.
    """
    page_resources = _resources({}) if resources is None else resources
    page_numbers = [_FIRST_PAGE_OBJECT + 2 * index for index in range(len(contents))]
    kids = b" ".join(b"%d 0 R" % number for number in page_numbers)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(contents)),
        _FONT,
    ]
    for number, content in zip(page_numbers, contents, strict=True):
        if content is None:
            objects += [_PAGE % (page_resources, b""), b"null"]
        else:
            contents_entry = b" /Contents %d 0 R" % (number + 1)
            objects += [_PAGE % (page_resources, contents_entry), content]
    return _assemble([*objects, *more_objects])


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
