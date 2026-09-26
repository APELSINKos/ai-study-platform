from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["json", "console"]


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

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
