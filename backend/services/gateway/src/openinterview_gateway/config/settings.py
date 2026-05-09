from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    gateway_host: str = "0.0.0.0"
    gateway_port: int = 9000
    gateway_service_token: str = "dev-service-token-change-me"

    database_url: str = Field(
        default="postgresql+asyncpg://openinterview:openinterview@localhost:5432/openinterview"
    )

    models_yaml_path: str = "/app/config/models.yaml"
    tiers_yaml_path: str = "/app/config/tiers.yaml"

    # Master key (for decrypting BYO keys read from the shared DB)
    openinterview_master_key: str = "dev-master-key-change-me-32bytes!"

    # HTTP client
    provider_timeout_s: float = 60.0

    # Admin/shared API keys per provider (used when user has no BYO key).
    # Read from env: SHARED_KEY_OPENAI, SHARED_KEY_OLLAMA, etc.
    shared_key_openai: str | None = None
    shared_key_anthropic: str | None = None
    shared_key_ollama: str | None = None
    shared_key_openrouter: str | None = None
    shared_key_together: str | None = None

    log_level: str = "INFO"
    log_json: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "openinterview-gateway"
    otel_exporter_otlp_endpoint: str | None = None
    otel_sample_ratio: float = 1.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
