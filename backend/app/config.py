"""Application configuration — loaded and validated at startup."""
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings, loaded from environment variables.

    Pydantic reads env vars at instantiation. Missing required fields
    raise a validation error immediately, so misconfiguration is caught
    at startup rather than deep inside a request handler.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # allow unknown env vars without error
    )

    # ------------------------------------------------------------------
    # LLM configuration
    # ------------------------------------------------------------------
    openai_api_key: SecretStr = Field(
        ...,
        description="OpenAI API key. Wrapped in SecretStr so it never "
        "appears in logs or __repr__ output.",
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model identifier for chat completions.",
    )

    # ------------------------------------------------------------------
    # Database configuration
    # ------------------------------------------------------------------
    postgres_user: str = Field(...)
    postgres_password: SecretStr = Field(...)
    postgres_db: str = Field(...)
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)

    # ------------------------------------------------------------------
    # Redis configuration
    # ------------------------------------------------------------------
    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)

    # ------------------------------------------------------------------
    # Application configuration
    # ------------------------------------------------------------------
    environment: Literal["development", "staging", "production"] = Field(
        default="development",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
    )

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection string for PostgreSQL."""
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Redis connection URL."""
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a singleton Settings instance.

    Using lru_cache ensures we only parse env vars once per process.
    FastAPI's Depends() can inject this into route handlers for testability.
    """
    return Settings()  # type: ignore[call-arg]