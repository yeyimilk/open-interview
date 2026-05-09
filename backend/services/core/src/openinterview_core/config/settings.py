"""Typed settings for the core service. Loaded once at startup."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    openinterview_env: Literal["local", "server"] = "local"

    # Storage
    storage_backend: Literal["local", "s3", "azure", "gcs"] = "local"
    openinterview_data_dir: str = "./data"
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_region: str | None = None
    azure_storage_account: str | None = None
    azure_storage_container: str | None = None
    azure_storage_prefix: str = ""
    gcs_bucket: str | None = None
    gcs_prefix: str = ""

    # DB
    database_url: str = Field(
        default="postgresql+asyncpg://openinterview:openinterview@localhost:5432/openinterview"
    )

    # Vector
    vector_backend: Literal["chroma"] = "chroma"
    chroma_url: str = "http://localhost:8000"

    # Gateway
    gateway_url: str = "http://localhost:9000"
    gateway_service_token: str = "dev-service-token-change-me"

    # Realtime (live-audio) gateway
    realtime_public_url: str = "ws://localhost:9200/ws/interview"
    openinterview_realtime_secret: str = "dev-realtime-secret-change-me-32bytes"
    realtime_internal_token: str = "dev-internal-token-change-me"
    realtime_ticket_ttl_s: int = 60

    # Security
    openinterview_master_key: str = "dev-master-key-change-me-32bytes!"
    jwt_secret: str = "dev-jwt-secret-change-me"
    jwt_access_ttl_s: int = 900
    jwt_refresh_ttl_s: int = 2_592_000
    openinterview_bootstrap_admin_email: str | None = None

    # Workers (used by core only to enqueue)
    worker_backend: Literal["arq", "rq", "celery"] = "arq"
    redis_url: str = "redis://localhost:6379/0"
    qa_generation_enqueue_required: bool = False
    tiers_yaml_path: str = "./config/tiers.yaml"

    # Optional OpenTelemetry exporter wiring.
    otel_enabled: bool = False
    otel_service_name: str = "openinterview-core"
    otel_exporter_otlp_endpoint: str | None = None
    otel_sample_ratio: float = 1.0

    # HTTP
    core_host: str = "0.0.0.0"
    core_port: int = 8000

    log_level: str = "INFO"
    log_json: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
