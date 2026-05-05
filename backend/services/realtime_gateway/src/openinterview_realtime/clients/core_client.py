"""Async HTTP client for the core service.

We use the new internal turn endpoint (`/internal/interviewer/{id}/turn`) which
takes a pre-transcribed user turn, persists it, runs the InterviewerAgent, and
SSE-streams the assistant tokens back. The realtime service authenticates with
a shared service token.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx


class CoreCallError(Exception):
    pass


class CoreClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_s: float = 120.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = service_token
        self._timeout = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "X-Internal-Token": self._token,
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }

    async def stream_interviewer_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        transcript: str,
        voice: dict | None,
    ) -> AsyncIterator[dict]:
        url = f"{self._base}/api/v1/internal/interviewer/{session_id}/turn"
        body = {
            "user_id": user_id,
            "transcript": transcript,
            "voice": voice or {},
        }
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            async with c.stream(
                "POST", url, headers=self._headers(), json=body
            ) as r:
                if r.status_code >= 400:
                    txt = await r.aread()
                    raise CoreCallError(
                        f"core turn {r.status_code}: "
                        f"{txt.decode(errors='ignore')[:300]}"
                    )
                buf = ""
                async for chunk in r.aiter_text():
                    buf += chunk
                    while "\n\n" in buf:
                        block, buf = buf.split("\n\n", 1)
                        ev = _parse_sse_block(block)
                        if ev is not None:
                            yield ev


def _parse_sse_block(block: str) -> dict | None:
    name = "message"
    data = ""
    for line in block.splitlines():
        if line.startswith("event: "):
            name = line[7:].strip()
        elif line.startswith("data: "):
            data += line[6:]
    if not data:
        return None
    try:
        payload = json.loads(data)
    except Exception:
        payload = {"raw": data}
    if isinstance(payload, dict):
        payload.setdefault("type", name)
    return {"event": name, "data": payload}
