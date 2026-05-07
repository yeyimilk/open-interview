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

    openinterview_realtime_secret: str = "dev-realtime-secret-change-me-32bytes"
    realtime_internal_token: str = "dev-internal-token-change-me"

    realtime_max_turn_seconds: int = 90
    realtime_transcription_model: str = "gpt-4o-transcribe"
    realtime_noise_reduction: str | None = "near_field"
    realtime_turn_detection: str = "semantic_vad"
    realtime_vad_eagerness: str = "low"
    realtime_speaker_verifier_backend: str = "speechbrain"
    realtime_speaker_threshold: float = 0.25
    realtime_calibration_seconds: float = 5.0
    realtime_min_turn_audio_ms: int = 300
    realtime_min_transcript_confidence: float = 0.35
    realtime_turn_commit_delay_ms: int = 1200
    realtime_debug_audio_dir: str = ""

    log_level: str = "INFO"
    log_json: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
