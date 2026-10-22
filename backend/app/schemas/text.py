from typing import Final

_NUL: Final = "\x00"


def reject_nul(value: str) -> str:
    """Refuse text with the NUL character in a request field that is stored.

    PostgreSQL text cannot hold NUL; rejecting it here keeps it a 422 instead of a 500.
    """
    if _NUL in value:
        raise ValueError("must not contain the NUL character")
    return value
