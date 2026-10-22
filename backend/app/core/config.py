from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import (
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticUseDefault
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.models.document import MODEL_NAME_MAX_LENGTH

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["json", "console"]
ProviderMode = Literal["auto", "mock", "openai"]
ResolvedProvider = Literal["mock", "openai"]
StructuredOutputMode = Literal["json_schema", "json_object"]
# Recorded with every document the model processes, in a column of this length.
ModelName = Annotated[str, StringConstraints(max_length=MODEL_NAME_MAX_LENGTH)]

# Not a real secret: a known placeholder that the validator below rejects in production.
DEV_SECRET_KEY: Final = "dev-only-secret-key-not-for-production-use-0000"  # noqa: S105
MIN_SECRET_KEY_LENGTH: Final = 32
MIB: Final = 1024 * 1024
GIB: Final = 1024 * MIB
DEFAULT_OPENAI_BASE_URL: Final = "https://api.openai.com/v1"
# The most inputs the OpenAI embeddings endpoint accepts in one request.
MAX_EMBEDDING_BATCH_SIZE: Final = 2048
# compose.yaml passes these through as ${VAR:-}, so an unset variable arrives as "".
_BLANK_MEANS_DEFAULT_FIELDS: Final = (
    "llm_provider",
    "embedding_provider",
    "openai_api_key",
    "embedding_api_key",
    "llm_base_url",
    "embedding_base_url",
    "llm_model",
    "embedding_model",
)


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    """An API key together with the only base URL it may be sent to."""

    api_key: SecretStr
    base_url: str


class Settings(BaseSettings):
    """Application settings, read from environment variables (case-insensitive)."""

    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "AI Study Platform"
    environment: Environment = "development"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"
    database_url: str = "postgresql+psycopg://study:study@localhost:5433/study"
    redis_url: str = "redis://localhost:6380/0"
    metrics_token: SecretStr | None = None
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    access_token_ttl_minutes: PositiveInt = 15
    refresh_token_ttl_days: PositiveInt = 14
    refresh_reuse_grace_seconds: PositiveInt = 10
    cookie_secure: bool | None = None
    login_attempts_per_minute: PositiveInt = 10
    login_attempts_per_ip_per_minute: PositiveInt = 30
    login_attempts_per_email_per_hour: PositiveInt = 50
    registrations_per_hour: PositiveInt = 30

    storage_dir: Path = Path("/data/uploads")
    # The web app's /api proxy (next.config.ts) must pass this plus the multipart overhead.
    max_upload_bytes: PositiveInt = 20 * MIB
    max_pdf_pages: PositiveInt = 500
    max_document_chars: PositiveInt = 2_000_000
    chunk_size_chars: PositiveInt = 1200
    chunk_overlap_chars: NonNegativeInt = 200
    embedding_batch_size: Annotated[int, Field(ge=1, le=MAX_EMBEDDING_BATCH_SIZE)] = 64
    analysis_max_input_chars: PositiveInt = 12_000
    uploads_per_hour: PositiveInt = 60
    document_retries_per_hour: PositiveInt = 30
    max_active_documents_per_user: PositiveInt = 10
    max_storage_bytes_per_user: PositiveInt = GIB

    llm_provider: ProviderMode = "auto"
    embedding_provider: ProviderMode = "auto"
    openai_api_key: SecretStr | None = None
    embedding_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    embedding_base_url: str | None = None
    llm_model: ModelName = "gpt-5.4-mini"
    embedding_model: ModelName = "text-embedding-3-small"
    llm_structured_output: StructuredOutputMode = "json_schema"
    llm_timeout_seconds: PositiveFloat = 60.0
    embedding_timeout_seconds: PositiveFloat = 30.0
    llm_max_retries: NonNegativeInt = 1
    llm_max_output_tokens: PositiveInt = 1000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("metrics_token", mode="before")
    @classmethod
    def blank_token_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("secret_key", mode="before")
    @classmethod
    def blank_secret_key_uses_the_development_default(cls, value: object) -> object:
        return DEV_SECRET_KEY if value == "" else value

    @field_validator("cookie_secure", mode="before")
    @classmethod
    def blank_cookie_secure_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator(*_BLANK_MEANS_DEFAULT_FIELDS, mode="before")
    @classmethod
    def blank_pass_through_uses_the_default(cls, value: object) -> object:
        text = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(text, str) and not text.strip():
            raise PydanticUseDefault()
        return value

    @model_validator(mode="after")
    def _reject_a_weak_production_secret_key(self) -> Self:
        if not self.is_production:
            return self
        secret = self.secret_key.get_secret_value()
        if secret == DEV_SECRET_KEY:
            raise ValueError("SECRET_KEY must not be the development default in production.")
        if len(secret) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters in production."
            )
        return self

    @model_validator(mode="after")
    def _reject_an_overlap_as_long_as_the_chunk(self) -> Self:
        if self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS must be smaller than CHUNK_SIZE_CHARS.")
        return self

    @model_validator(mode="after")
    def _reject_a_provider_without_its_key(self) -> Self:
        if self.embedding_base_url is not None and self.embedding_api_key is None:
            raise ValueError(
                "EMBEDDING_BASE_URL needs EMBEDDING_API_KEY; a local server accepts any dummy key."
            )
        if self.llm_provider == "openai" and self.openai_api_key is None:
            raise ValueError("LLM_PROVIDER=openai needs OPENAI_API_KEY.")
        if self.embedding_provider == "openai" and self.embedding_endpoint is None:
            raise ValueError("EMBEDDING_PROVIDER=openai needs EMBEDDING_API_KEY or OPENAI_API_KEY.")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure

    @property
    def resolved_llm_provider(self) -> ResolvedProvider:
        if self.llm_provider == "auto":
            return "openai" if self.openai_api_key is not None else "mock"
        return self.llm_provider

    @property
    def resolved_embedding_provider(self) -> ResolvedProvider:
        if self.embedding_provider == "auto":
            return "openai" if self.embedding_endpoint is not None else "mock"
        return self.embedding_provider

    @property
    def embedding_endpoint(self) -> ProviderEndpoint | None:
        # A key is resolved together with its URL, so it never reaches a host it was not
        # issued for: chat and embeddings often come from different vendors.
        if self.embedding_api_key is not None:
            return ProviderEndpoint(
                api_key=self.embedding_api_key,
                base_url=self.embedding_base_url or DEFAULT_OPENAI_BASE_URL,
            )
        if self.embedding_base_url is None and self.openai_api_key is not None:
            return ProviderEndpoint(
                api_key=self.openai_api_key,
                base_url=self.llm_base_url or DEFAULT_OPENAI_BASE_URL,
            )
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
