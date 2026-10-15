from collections.abc import Iterator
from typing import Final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.pagination import Page, PageParams, PageParamsDep

ITEMS_PATH: Final = "/test/items"
TOTAL_ITEMS: Final = 12_345


class ItemOut(BaseModel):
    name: str


class ItemPage(Page[ItemOut]):
    pass


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    @app.get(ITEMS_PATH)
    def list_items(params: PageParamsDep) -> ItemPage:
        item = ItemOut(name=f"offset {params.offset}, limit {params.limit}")
        return ItemPage(
            items=[item], total=TOTAL_ITEMS, page=params.page, page_size=params.page_size
        )

    with TestClient(app) as test_client:
        yield test_client


def test_offset_skips_every_earlier_page() -> None:
    assert PageParams().offset == 0
    assert PageParams(page=3, page_size=50).offset == 100
    assert PageParams(page=3, page_size=50).limit == 50


def test_the_first_page_of_twenty_items_is_the_default(client: TestClient) -> None:
    response = client.get(ITEMS_PATH)

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"name": "offset 0, limit 20"}],
        "total": TOTAL_ITEMS,
        "page": 1,
        "page_size": 20,
    }


def test_the_largest_page_and_page_size_are_accepted(client: TestClient) -> None:
    response = client.get(ITEMS_PATH, params={"page": 10_000, "page_size": 100})

    assert response.status_code == 200
    body = response.json()
    assert (body["page"], body["page_size"]) == (10_000, 100)
    assert body["items"] == [{"name": "offset 999900, limit 100"}]


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ({"page_size": 101}, "page_size"),
        ({"page_size": 0}, "page_size"),
        ({"page": 0}, "page"),
        ({"page": 10_001}, "page"),
        # Past the bigint range an OFFSET would fail in the database instead.
        ({"page": 10**19}, "page"),
    ],
    ids=["page_size-101", "page_size-0", "page-0", "page-10001", "page-10e19"],
)
def test_out_of_range_page_parameters_are_rejected(
    client: TestClient, query: dict[str, int], field: str
) -> None:
    response = client.get(ITEMS_PATH, params=query)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert [detail["field"] for detail in error["details"]] == [field]


def test_a_page_subclass_appears_in_openapi_under_its_own_name(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert schemas["ItemPage"]["properties"]["items"]["items"] == {
        "$ref": "#/components/schemas/ItemOut"
    }
    assert not [name for name in schemas if name.startswith("Page")]


def test_page_parameters_are_documented_with_their_bounds(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][ITEMS_PATH]["get"]

    bounds = {
        parameter["name"]: (
            parameter["schema"]["minimum"],
            parameter["schema"]["maximum"],
            parameter["schema"]["default"],
        )
        for parameter in operation["parameters"]
    }
    assert bounds == {"page": (1, 10_000, 1), "page_size": (1, 100, 20)}
