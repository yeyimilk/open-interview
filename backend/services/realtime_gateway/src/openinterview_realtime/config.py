from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    realtime_host: str = "0.0.0.0"
    realtime_port: int = 9200

    core_url: str = "http://localhost:8000"
    gateway_url: str = "http://localhost:9100"
    gateway_service_token: str = "dev-service-token-change-me"

    openinterview_realtime_secret: str = "dev-realtime-secret-change-me"
    realtime_internal_token: str = "dev-internal-token-change-me"

    realtime_max_turn_seconds: int = 90
    realtime_vad_silence_ms: int = 700

    log_level: str = "INFO"
    log_json: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
