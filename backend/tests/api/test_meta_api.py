from http import HTTPStatus
from pathlib import Path
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import MIB, Settings
from app.main import create_app

_META_PATH: Final = "/api/v1/meta"
_CHAT_KEY: Final = "sk-chat-key-used-only-in-tests-0123456789abcdef"
_EMBEDDING_KEY: Final = "sk-embedding-key-used-only-in-tests-0123456789"
_CHAT_URL: Final = "https://openrouter.ai/api/v1"
_EMBEDDING_URL: Final = "https://embeddings.example.com/v1"
_CHAT_MODEL: Final = "openai/gpt-5.4-mini"
_EMBEDDING_MODEL: Final = "text-embedding-3-small"
_OFFLINE_CHAT_MODEL: Final = "mock-heuristic-v1"
_OFFLINE_EMBEDDING_MODEL: Final = "mock-hashing-v1"


def _settings(storage_dir: Path, **values: Any) -> Settings:
    return Settings(environment="test", storage_dir=storage_dir, **values)


def _get_meta(settings: Settings) -> dict[str, Any]:
    with TestClient(create_app(settings)) as client:
        response = client.get(_META_PATH)
    assert response.status_code == HTTPStatus.OK
    body: dict[str, Any] = response.json()
    return body


def test_meta_needs_no_sign_in_and_describes_the_upload_rules(
    client: TestClient, settings: Settings
) -> None:
    response = client.get(_META_PATH)

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "max_upload_bytes": settings.max_upload_bytes,
        "allowed_extensions": [".pdf", ".md", ".txt"],
        "max_pdf_pages": settings.max_pdf_pages,
        "max_active_documents_per_user": settings.max_active_documents_per_user,
        "max_storage_bytes_per_user": settings.max_storage_bytes_per_user,
        "ai": {
            "mode": "offline",
            "chat_model": _OFFLINE_CHAT_MODEL,
            "embedding_model": _OFFLINE_EMBEDDING_MODEL,
        },
    }


def test_meta_follows_the_settings(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        llm_provider="mock",
        embedding_provider="mock",
        max_upload_bytes=5 * MIB,
        max_pdf_pages=40,
        max_active_documents_per_user=3,
        max_storage_bytes_per_user=200 * MIB,
    )

    body = _get_meta(settings)

    assert (
        body["max_upload_bytes"],
        body["max_pdf_pages"],
        body["max_active_documents_per_user"],
        body["max_storage_bytes_per_user"],
    ) == (5 * MIB, 40, 3, 200 * MIB)


def test_meta_names_the_live_models_but_never_their_keys_or_addresses(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        llm_provider="openai",
        openai_api_key=SecretStr(_CHAT_KEY),
        llm_base_url=_CHAT_URL,
        llm_model=_CHAT_MODEL,
        embedding_provider="openai",
        embedding_api_key=SecretStr(_EMBEDDING_KEY),
        embedding_base_url=_EMBEDDING_URL,
        embedding_model=_EMBEDDING_MODEL,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get(_META_PATH)

    assert response.json()["ai"] == {
        "mode": "live",
        "chat_model": _CHAT_MODEL,
        "embedding_model": _EMBEDDING_MODEL,
    }
    for secret in (
        _CHAT_KEY,
        _EMBEDDING_KEY,
        _CHAT_URL,
        _EMBEDDING_URL,
        "openrouter.ai",
        "embeddings.example.com",
    ):
        assert secret not in response.text


@pytest.mark.parametrize(
    ("values", "ai"),
    [
        (
            {
                "llm_provider": "openai",
                "openai_api_key": SecretStr(_CHAT_KEY),
                "llm_model": _CHAT_MODEL,
                "embedding_provider": "mock",
            },
            {
                "mode": "offline",
                "chat_model": _CHAT_MODEL,
                "embedding_model": _OFFLINE_EMBEDDING_MODEL,
            },
        ),
        (
            {
                "llm_provider": "mock",
                "embedding_provider": "openai",
                "embedding_api_key": SecretStr(_EMBEDDING_KEY),
                "embedding_model": _EMBEDDING_MODEL,
            },
            {
                "mode": "offline",
                "chat_model": _OFFLINE_CHAT_MODEL,
                "embedding_model": _EMBEDDING_MODEL,
            },
        ),
        (
            # With a key set, auto picks the live models; embeddings share the chat endpoint.
            {
                "llm_provider": "auto",
                "embedding_provider": "auto",
                "openai_api_key": SecretStr(_CHAT_KEY),
                "embedding_api_key": None,
                "llm_model": _CHAT_MODEL,
                "embedding_model": _EMBEDDING_MODEL,
            },
            {"mode": "live", "chat_model": _CHAT_MODEL, "embedding_model": _EMBEDDING_MODEL},
        ),
        (
            {
                "llm_provider": "auto",
                "embedding_provider": "auto",
                "openai_api_key": None,
                "embedding_api_key": None,
            },
            {
                "mode": "offline",
                "chat_model": _OFFLINE_CHAT_MODEL,
                "embedding_model": _OFFLINE_EMBEDDING_MODEL,
            },
        ),
    ],
    ids=["offline-embeddings", "offline-analysis", "auto-with-a-key", "auto-without-keys"],
)
def test_meta_is_offline_whenever_either_model_is_the_built_in_one(
    tmp_path: Path, values: dict[str, Any], ai: dict[str, str]
) -> None:
    assert _get_meta(_settings(tmp_path, **values))["ai"] == ai


def test_openapi_documents_meta_as_a_public_route(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    operation = schema["paths"][_META_PATH]["get"]
    assert operation["tags"] == ["meta"]
    assert "security" not in operation
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MetaOut"
    }
    schemas = schema["components"]["schemas"]
    meta = schemas["MetaOut"]
    assert set(meta["required"]) == set(meta["properties"])
    assert meta["properties"]["ai"]["$ref"] == "#/components/schemas/AiInfo"
    assert schemas["AiInfo"]["properties"]["mode"]["$ref"] == "#/components/schemas/AiMode"
    assert schemas["AiMode"]["enum"] == ["offline", "live"]
