"""Audio transcription endpoint: posts a tiny WAV upload and asserts the
gateway receives the right payload + the API returns the canned text."""
from __future__ import annotations

import io
import os
import struct

import pytest

pytest.importorskip("aiosqlite")

from httpx import ASGITransport, AsyncClient

from openinterview_core.app import create_app
from openinterview_core.config import Settings
from openinterview_core.infra.vector import InMemoryVectorStore
from openinterview_schemas import TokenUsage, TranscriptionResponse


class FakeGatewayForAudio:
    def __init__(self) -> None:
        self.transcribe_calls: list[dict] = []

    async def transcribe(self, *, user_id, logical_model, audio, mime, language=None):
        self.transcribe_calls.append(
            {"user_id": user_id, "model": logical_model, "mime": mime, "lang": language, "size": len(audio)}
        )
        return TranscriptionResponse(
            text=f"transcribed:{len(audio)}",
            model=logical_model,
            provider="fake",
            usage=TokenUsage(),
        )


def _settings(tmp_path) -> Settings:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        openinterview_data_dir=str(tmp_path),
    )  # type: ignore[call-arg]


def _tiny_wav() -> bytes:
    # Minimal valid 8-bit mono WAV with 4 silent samples.
    samples = b"\x80\x80\x80\x80"
    data_chunk = b"data" + struct.pack("<I", len(samples)) + samples
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)
    body = b"WAVE" + fmt_chunk + data_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


async def _register_login(c: AsyncClient, email: str) -> str:
    await c.post("/api/v1/auth/register", json={
        "email": email, "password": "hunter2hunter2", "display_name": "U"
    })
    r = await c.post("/api/v1/auth/login", json={
        "email": email, "password": "hunter2hunter2",
    })
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_transcribe_endpoint_uploads_and_returns_text(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    fake = FakeGatewayForAudio()
    app.state.gateway = fake
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "a@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            wav = _tiny_wav()
            files = {"file": ("clip.wav", wav, "audio/wav")}
            r = await c.post(
                "/api/v1/audio/transcribe",
                headers=h, files=files, data={"language": "en"},
            )
            assert r.status_code == 200, r.text
            assert r.json() == {"text": f"transcribed:{len(wav)}"}

            # Bad mime rejected.
            r2 = await c.post(
                "/api/v1/audio/transcribe",
                headers=h,
                files={"file": ("a.bin", b"x", "application/octet-stream")},
            )
            assert r2.status_code == 415

            assert fake.transcribe_calls
            call = fake.transcribe_calls[0]
            assert call["mime"] == "audio/wav"
            assert call["lang"] == "en"
            assert call["size"] == len(wav)
            assert call["model"] == "stt-default"


@pytest.mark.asyncio
async def test_transcribe_requires_auth(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.gateway = FakeGatewayForAudio()
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post(
                "/api/v1/audio/transcribe",
                files={"file": ("clip.wav", _tiny_wav(), "audio/wav")},
            )
            assert r.status_code == 401
