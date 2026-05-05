"""Thin async HTTP client for the GenAI gateway.

The realtime service only needs voice analysis (STT + delivery features). We
keep this client minimal to stay loosely coupled from the rest of the codebase
so this folder can be split out as a micro-service later.
"""
from __future__ import annotations

import base64

import httpx


class GatewayCallError(Exception):
    pass


class GatewayClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_s: float = 60.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = service_token
        self._timeout = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def analyze_voice(
        self,
        *,
        user_id: str,
        audio: bytes,
        mime: str,
        language: str | None = None,
    ) -> dict:
        body = {
            "user_id": user_id,
            "logical_model": "voice-analysis-default",
            "audio_b64": base64.b64encode(audio).decode("ascii"),
            "mime": mime,
            "language": language,
        }
        url = f"{self._base}/v1/audio/analyze"
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(url, headers=self._headers(), json=body)
        if r.status_code >= 400:
            raise GatewayCallError(
                f"gateway analyze {r.status_code}: {r.text[:300]}"
            )
        return r.json()
