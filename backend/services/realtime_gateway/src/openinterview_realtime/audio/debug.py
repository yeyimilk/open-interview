from __future__ import annotations

import hashlib
import json
import wave
from dataclasses import dataclass
from pathlib import Path

from openinterview_logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class AudioDebugContext:
    session_id: str
    user_id: str
    sample_rate: int
    channels: int
    audio_format: str


class AudioDebugDumper:
    """Optional local WAV/JSON dumper for live-audio development.

    This is deliberately isolated from `LiveSession` so production turn
    orchestration does not depend on filesystem details. Passing an empty root
    disables all writes.
    """

    def __init__(self, root: str = "") -> None:
        self._root = root.strip()

    def duration_s(
        self, audio: bytes | bytearray, *, sample_rate: int, channels: int = 1
    ) -> float:
        return len(audio) / max(1, sample_rate * max(1, channels) * 2)

    def dump(
        self,
        *,
        context: AudioDebugContext,
        label: str,
        audio: bytes | bytearray,
        transcript: str | None = None,
        metadata: dict | None = None,
    ) -> str | None:
        if not self._root or not audio:
            return None
        try:
            root = Path(self._root).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            safe_label = "".join(
                c if c.isalnum() or c in ("-", "_") else "_" for c in label
            )[:80]
            raw = bytes(audio)
            digest = hashlib.sha1(raw).hexdigest()[:10]
            name = f"{context.session_id}_{safe_label}_{digest}"
            wav_path = root / f"{name}.wav"
            with wave.open(str(wav_path), "wb") as wav:
                wav.setnchannels(max(1, context.channels))
                wav.setsampwidth(2)
                wav.setframerate(context.sample_rate)
                wav.writeframes(raw)

            meta = {
                "session_id": context.session_id,
                "user_id": context.user_id,
                "sample_rate": context.sample_rate,
                "channels": context.channels,
                "audio_format": context.audio_format,
                "audio_bytes": len(raw),
                "duration_s": self.duration_s(
                    raw,
                    sample_rate=context.sample_rate,
                    channels=context.channels,
                ),
                "wav_path": str(wav_path),
                **(metadata or {}),
            }
            if transcript is not None:
                meta["transcript"] = transcript
            meta_path = root / f"{name}.json"
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return str(wav_path)
        except Exception as e:  # noqa: BLE001
            log.warning("live_audio_debug_dump_failed", error=str(e))
            return None
