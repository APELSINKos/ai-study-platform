import re
from typing import Final

_NUL: Final = "\x00"
# Surrogates are halves of a UTF-16 pair; alone, no UTF-8 text can hold one.
_SURROGATE_RE: Final = re.compile(r"[\ud800-\udfff]")


def reject_nul(value: str) -> str:
    """Refuse text with the NUL character in a request field that is stored.

    PostgreSQL text cannot hold NUL; rejecting it here keeps it a 422 instead of a 500.
    """
    if _NUL in value:
        raise ValueError("must not contain the NUL character")
    return value


def has_surrogate(value: str) -> bool:
    """Whether the text holds a surrogate, which makes encoding it as UTF-8 fail.

    A form body in a charset such as UTF-7 can put one into any field of the form.
    """
    return _SURROGATE_RE.search(value) is not None
