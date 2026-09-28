from functools import lru_cache
from typing import Annotated, Final, Literal, Self

from pydantic import PositiveInt, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["json", "console"]

# Not a real secret: a known placeholder that the validator below rejects in production.
DEV_SECRET_KEY: Final = "dev-only-secret-key-not-for-production-use-0000"  # noqa: S105
MIN_SECRET_KEY_LENGTH: Final = 32


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

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure


@lru_cache
def get_settings() -> Settings:
    return Settings()
