from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Query
from pydantic import BaseModel, Field

# Bounding the page also bounds the offset, which must fit the database's bigint.
MAX_PAGE: Final = 10_000
MAX_PAGE_SIZE: Final = 100
DEFAULT_PAGE_SIZE: Final = 20


class Page[T](BaseModel):
    """One page of a list; each resource subclasses it to get its own schema name."""

    items: list[T]
    total: int = Field(description="Number of items on all pages.")
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class PageParams:
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


PageParamsDep = Annotated[PageParams, Depends()]
