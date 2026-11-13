"""Typed, environment-driven application configuration."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Runtime configuration with explicit development/test/production profiles.

    Environment variables are the final override layer. The ``environment`` field
    selects the profile defaults, while explicit values always win.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
    )

    app_name: str = Field(default="Veristock", min_length=1)
    app_version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_prefix: str = "/api"
    allow_self_registration: bool = False
    jwt_secret_key: SecretStr | None = Field(default=None, min_length=32)
    access_token_lifetime_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_lifetime_seconds: int = Field(default=604800, ge=3600)
    database_url: str = "sqlite+aiosqlite:///./backbone.db"
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_pre_ping: bool = True
    log_level: str = "INFO"
    log_json: bool = False
    ai_provider: str | None = None
    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    stocktake_evidence_storage_dir: Path = Path(".data/stocktake-evidence")
    stocktake_evidence_max_bytes: int = Field(default=8 * 1024 * 1024, ge=1024, le=32 * 1024 * 1024)
    cors_origins: list[str] = Field(default_factory=list)
    cors_allow_credentials: bool = False
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: [
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ]
    )
    cors_allow_headers: list[str] = Field(
        default_factory=lambda: ["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"]
    )

    @model_validator(mode="after")
    def validate_profile(self) -> "Settings":
        if self.ai_provider is not None:
            if self.ai_provider != "openai-compatible":
                raise ValueError("AI_PROVIDER must be openai-compatible when configured")
            if not self.ai_base_url or not self.ai_model:
                raise ValueError(
                    "AI_BASE_URL and AI_MODEL are required when AI_PROVIDER is configured"
                )
        if self.environment is Environment.PRODUCTION:
            if self.debug:
                raise ValueError("debug must be false in production")
            if not self.database_url.startswith("postgresql+asyncpg://"):
                raise ValueError("production requires a PostgreSQL asyncpg DATABASE_URL")
            self.log_json = True
        if self.environment is Environment.TEST:
            self.debug = False
        return self

    @classmethod
    def for_profile(cls, profile: Environment | str) -> "Settings":
        """Build deterministic settings for tests, local development, or production."""
        environment = Environment(profile)
        if environment is Environment.TEST:
            return cls(
                environment=environment,
                database_url="sqlite+aiosqlite:///:memory:",
                log_json=False,
            )
        if environment is Environment.PRODUCTION:
            return cls(
                environment=environment,
                database_url="postgresql+asyncpg://backbone:backbone@localhost:5432/backbone",
                log_json=True,
            )
        return cls(environment=environment)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings object."""
    return Settings()
