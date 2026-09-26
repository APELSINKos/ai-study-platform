from typing import Final

MS_PER_SECOND: Final = 1000
_MS_PRECISION: Final = 1


def to_ms(seconds: float) -> float:
    return round(seconds * MS_PER_SECOND, _MS_PRECISION)
