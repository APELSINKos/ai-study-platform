import hashlib
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, Final

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.documents.storage import FileStorage
from app.models.document import Document, DocumentStatus
from app.repositories.documents import DocumentRepository
from tests.api.conftest import csrf_headers

pytestmark = pytest.mark.integration

_WORKSPACES_PATH: Final = "/api/v1/workspaces"
_EMPTY_STATS: Final = {
    "document_count": 0,
    "ready_count": 0,
    "processing_count": 0,
    "failed_count": 0,
    "estimated_study_minutes": 0,
}
# Fields a row in this status must carry to pass the documents table's CHECKs.
_STATUS_FIELDS: Final[dict[DocumentStatus, dict[str, object]]] = {
    "ready": {
        "chunk_count": 4,
        "embedding_model": "mock-hashing-v1",
        "processed_at": datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
    },
    "failed": {"error_code": "pdf_unreadable"},
}


def _path(workspace_id: str) -> str:
    return f"{_WORKSPACES_PATH}/{workspace_id}"


def _create(client: TestClient, **fields: object) -> dict[str, Any]:
    response = client.post(
        _WORKSPACES_PATH, json={"name": "Algorithms", **fields}, headers=csrf_headers(client)
    )
    assert response.status_code == HTTPStatus.CREATED
    body: dict[str, Any] = response.json()
    return body


def _patch(client: TestClient, workspace_id: str, changes: dict[str, object]) -> dict[str, Any]:
    response = client.patch(_path(workspace_id), json=changes, headers=csrf_headers(client))
    assert response.status_code == HTTPStatus.OK
    body: dict[str, Any] = response.json()
    return body


def _list(client: TestClient, **params: int) -> dict[str, Any]:
    response = client.get(_WORKSPACES_PATH, params=params)
    assert response.status_code == HTTPStatus.OK
    body: dict[str, Any] = response.json()
    return body


def _add_document(
    session: Session, workspace_id: str, status: DocumentStatus, **values: object
) -> None:
    document_id = uuid.uuid4()
    fields: dict[str, object] = {
        "id": document_id,
        "workspace_id": uuid.UUID(workspace_id),
        "original_filename": "notes.md",
        "content_type": "text/markdown",
        "size_bytes": 2048,
        "sha256": hashlib.sha256(document_id.bytes).hexdigest(),
        "storage_key": f"{workspace_id}/{document_id}.md",
        "status": status,
        **_STATUS_FIELDS.get(status, {}),
    }
    fields.update(values)
    DocumentRepository(session).add(Document(**fields))


def _store_file(storage: FileStorage, workspace_id: str) -> str:
    key = storage.key_for(uuid.UUID(workspace_id), uuid.uuid4(), ".md")
    with storage.temp_file() as temp:
        temp.write_bytes(b"# Lecture notes\n")
        storage.commit_temp(temp, key)
    return key


def _assert_error(response: httpx2.Response, status: HTTPStatus, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


# --- create and read --------------------------------------------------------------


def test_create_returns_the_new_workspace_with_empty_stats(user_client: TestClient) -> None:
    response = user_client.post(
        _WORKSPACES_PATH,
        json={
            "name": "  Algorithms  ",
            "description": "Graphs and trees",
            "exam_date": "2027-01-20",
        },
        headers=csrf_headers(user_client),
    )

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["name"] == "Algorithms"
    assert body["description"] == "Graphs and trees"
    assert body["exam_date"] == "2027-01-20"
    assert body["stats"] == _EMPTY_STATS
    assert body["created_at"] == body["updated_at"]
    assert "owner_id" not in body


def test_create_needs_only_a_name_and_stores_a_blank_description_as_none(
    user_client: TestClient,
) -> None:
    bare = _create(user_client, name="Bare")
    blank = _create(user_client, name="Blank", description="   \n ")

    assert (bare["description"], bare["exam_date"]) == (None, None)
    assert blank["description"] is None


def test_get_returns_the_workspace(user_client: TestClient) -> None:
    created = _create(user_client, description="Graphs and trees")

    response = user_client.get(_path(created["id"]))

    assert response.status_code == HTTPStatus.OK
    assert response.json() == created


def test_the_longest_name_and_description_are_accepted_after_trimming(
    user_client: TestClient,
) -> None:
    name = "N" * 120
    description = "D" * 1000

    created = _create(user_client, name=f"  {name}  ", description=f"\n{description}\n")

    assert (created["name"], created["description"]) == (name, description)


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "name"),
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "N" * 121}, "name"),
        ({"name": "Algo\x00rithms"}, "name"),
        ({"name": "Algorithms", "description": "D" * 1001}, "description"),
        ({"name": "Algorithms", "description": "Graphs\x00"}, "description"),
        ({"name": "Algorithms", "exam_date": "20.01.2027"}, "exam_date"),
    ],
    ids=[
        "missing-name",
        "empty-name",
        "blank-name",
        "long-name",
        "nul-in-name",
        "long-description",
        "nul-in-description",
        "bad-date",
    ],
)
def test_create_rejects_invalid_fields(
    user_client: TestClient, payload: dict[str, object], field: str
) -> None:
    response = user_client.post(_WORKSPACES_PATH, json=payload, headers=csrf_headers(user_client))

    _assert_error(response, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert [detail["field"] for detail in response.json()["error"]["details"]] == [field]
    assert _list(user_client)["total"] == 0


def test_an_unknown_workspace_is_not_found(user_client: TestClient) -> None:
    response = user_client.get(_path(str(uuid.uuid4())))

    _assert_error(response, HTTPStatus.NOT_FOUND, "workspace_not_found")


def test_a_malformed_workspace_id_is_a_validation_error(user_client: TestClient) -> None:
    response = user_client.get(_path("not-a-uuid"))

    _assert_error(response, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == "workspace_id"


def test_workspaces_need_a_signed_in_user(auth_client: TestClient) -> None:
    response = auth_client.get(_WORKSPACES_PATH)

    _assert_error(response, HTTPStatus.UNAUTHORIZED, "not_authenticated")
    assert response.headers["www-authenticate"] == "Bearer"


# --- list -------------------------------------------------------------------------


def test_the_list_puts_the_most_recently_updated_workspace_first(user_client: TestClient) -> None:
    first = _create(user_client, name="First")
    _create(user_client, name="Second")
    _create(user_client, name="Third")

    before = _list(user_client)
    _patch(user_client, first["id"], {"description": "Revised"})
    after = _list(user_client)

    assert [item["name"] for item in before["items"]] == ["Third", "Second", "First"]
    assert [item["name"] for item in after["items"]] == ["First", "Third", "Second"]
    assert (after["total"], after["page"], after["page_size"]) == (3, 1, 20)


def test_the_list_is_paginated(user_client: TestClient) -> None:
    for number in range(1, 6):
        _create(user_client, name=f"Workspace {number}")

    second_page = _list(user_client, page=2, page_size=2)
    last_page = _list(user_client, page=3, page_size=2)
    beyond = _list(user_client, page=4, page_size=2)

    assert [item["name"] for item in second_page["items"]] == ["Workspace 3", "Workspace 2"]
    assert (second_page["total"], second_page["page"], second_page["page_size"]) == (5, 2, 2)
    assert [item["name"] for item in last_page["items"]] == ["Workspace 1"]
    assert (beyond["items"], beyond["total"]) == ([], 5)


def test_stats_count_the_documents_in_each_state(
    user_client: TestClient, db_session: Session
) -> None:
    workspace = _create(user_client)
    empty = _create(user_client, name="Empty")
    for status in ("uploaded", "processing", "indexing", "failed"):
        _add_document(db_session, workspace["id"], status)
    _add_document(db_session, workspace["id"], "ready", estimated_study_minutes=25)
    _add_document(db_session, workspace["id"], "ready", estimated_study_minutes=15)
    # Minutes of a document that is not ready yet stay out of the estimate.
    _add_document(db_session, workspace["id"], "indexing", estimated_study_minutes=60)
    expected = {
        "document_count": 7,
        "ready_count": 2,
        "processing_count": 4,
        "failed_count": 1,
        "estimated_study_minutes": 40,
    }

    detail = user_client.get(_path(workspace["id"])).json()
    listed = {item["name"]: item["stats"] for item in _list(user_client)["items"]}

    assert detail["stats"] == expected
    assert listed == {"Algorithms": expected, "Empty": _EMPTY_STATS}
    assert empty["stats"] == _EMPTY_STATS


# --- update -----------------------------------------------------------------------


def test_patch_changes_only_the_fields_sent(user_client: TestClient) -> None:
    created = _create(user_client, description="Graphs and trees", exam_date="2027-01-20")

    renamed = _patch(user_client, created["id"], {"name": "  Graph theory  "})

    assert renamed["name"] == "Graph theory"
    assert (renamed["description"], renamed["exam_date"]) == ("Graphs and trees", "2027-01-20")
    assert renamed["created_at"] == created["created_at"]
    assert datetime.fromisoformat(renamed["updated_at"]) > datetime.fromisoformat(
        created["updated_at"]
    )
    assert user_client.get(_path(created["id"])).json() == renamed


def test_patch_with_null_clears_the_description_and_the_exam_date(
    user_client: TestClient,
) -> None:
    created = _create(user_client, description="Graphs and trees", exam_date="2027-01-20")

    cleared = _patch(user_client, created["id"], {"description": None, "exam_date": None})
    dated = _patch(user_client, created["id"], {"exam_date": "2027-02-01"})

    assert (cleared["name"], cleared["description"], cleared["exam_date"]) == (
        "Algorithms",
        None,
        None,
    )
    assert (dated["description"], dated["exam_date"]) == (None, "2027-02-01")


@pytest.mark.parametrize(
    "changes",
    [
        {"name": None},
        {"name": "   "},
        {"name": "N" * 121},
        {"description": "D" * 1001},
        {"exam_date": "tomorrow"},
    ],
    ids=["null-name", "blank-name", "long-name", "long-description", "bad-date"],
)
def test_patch_rejects_invalid_fields_and_changes_nothing(
    user_client: TestClient, changes: dict[str, object]
) -> None:
    created = _create(user_client, description="Graphs and trees")

    response = user_client.patch(
        _path(created["id"]), json=changes, headers=csrf_headers(user_client)
    )

    _assert_error(response, HTTPStatus.UNPROCESSABLE_ENTITY, "validation_error")
    assert [detail["field"] for detail in response.json()["error"]["details"]] == list(changes)
    assert user_client.get(_path(created["id"])).json() == created


# --- delete -----------------------------------------------------------------------


def test_delete_removes_the_workspace_and_its_folder(
    user_client: TestClient, integration_settings: Settings
) -> None:
    storage = FileStorage(integration_settings.storage_dir)
    workspace = _create(user_client)
    _store_file(storage, workspace["id"])
    kept = _create(user_client, name="Kept")
    kept_key = _store_file(storage, kept["id"])

    response = user_client.delete(_path(workspace["id"]), headers=csrf_headers(user_client))

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert response.content == b""
    _assert_error(
        user_client.get(_path(workspace["id"])), HTTPStatus.NOT_FOUND, "workspace_not_found"
    )
    assert not storage.path_for(workspace["id"]).exists()
    assert storage.path_for(kept_key).exists()
    assert [item["id"] for item in _list(user_client)["items"]] == [kept["id"]]


def test_delete_of_a_workspace_without_files_succeeds(user_client: TestClient) -> None:
    workspace = _create(user_client)

    response = user_client.delete(_path(workspace["id"]), headers=csrf_headers(user_client))

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert _list(user_client)["total"] == 0


# --- two users and CSRF -----------------------------------------------------------


def test_another_users_workspace_is_not_found_and_stays_unchanged(
    user_client: TestClient, other_user_client: TestClient, integration_settings: Settings
) -> None:
    storage = FileStorage(integration_settings.storage_dir)
    workspace = _create(user_client, name="Mine", description="Private notes")
    key = _store_file(storage, workspace["id"])
    path = _path(workspace["id"])

    responses = [
        other_user_client.get(path),
        other_user_client.patch(
            path,
            json={"name": "Taken", "description": None},
            headers=csrf_headers(other_user_client),
        ),
        other_user_client.delete(path, headers=csrf_headers(other_user_client)),
    ]

    for response in responses:
        _assert_error(response, HTTPStatus.NOT_FOUND, "workspace_not_found")
    assert user_client.get(path).json() == workspace
    assert storage.path_for(key).exists()
    assert _list(other_user_client)["total"] == 0


def test_cookie_requests_that_change_workspaces_need_the_csrf_header(
    user_client: TestClient,
) -> None:
    workspace = _create(user_client, name="Original")
    path = _path(workspace["id"])

    responses = [
        user_client.post(_WORKSPACES_PATH, json={"name": "Another"}),
        user_client.patch(path, json={"name": "Changed"}),
        user_client.delete(path),
    ]

    for response in responses:
        _assert_error(response, HTTPStatus.FORBIDDEN, "csrf_failed")
    assert _list(user_client)["items"] == [workspace]


# --- OpenAPI ----------------------------------------------------------------------


def test_openapi_documents_the_workspace_routes_and_their_errors(
    auth_client: TestClient,
) -> None:
    schema = auth_client.get("/openapi.json").json()

    collection = schema["paths"]["/api/v1/workspaces"]
    item = schema["paths"]["/api/v1/workspaces/{workspace_id}"]
    statuses = {
        "list": set(collection["get"]["responses"]),
        "create": set(collection["post"]["responses"]),
        "get": set(item["get"]["responses"]),
        "update": set(item["patch"]["responses"]),
        "delete": set(item["delete"]["responses"]),
    }
    assert statuses == {
        "list": {"200", "401", "422"},
        "create": {"201", "401", "403", "422"},
        "get": {"200", "401", "404", "422"},
        "update": {"200", "401", "403", "404", "422"},
        "delete": {"204", "401", "403", "404", "422"},
    }
    assert collection["get"]["tags"] == ["workspaces"]
    page = schema["components"]["schemas"]["WorkspacePage"]
    assert page["properties"]["items"]["items"] == {"$ref": "#/components/schemas/WorkspaceOut"}


def test_openapi_documents_the_name_of_a_patch_as_optional_but_never_null(
    auth_client: TestClient,
) -> None:
    schemas = auth_client.get("/openapi.json").json()["components"]["schemas"]

    update = schemas["WorkspaceUpdateRequest"]
    assert update["properties"]["name"]["type"] == "string"
    assert "anyOf" not in update["properties"]["name"]
    assert "required" not in update
    assert schemas["WorkspaceCreateRequest"]["required"] == ["name"]
