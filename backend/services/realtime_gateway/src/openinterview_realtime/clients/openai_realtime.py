from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import websockets


class RealtimeTranscriberError(Exception):
    pass


class OpenAIRealtimeTranscriber:
    def __init__(self, *, ws_url: str, client_secret: str) -> None:
        self._ws_url = ws_url
        self._client_secret = client_secret
        self._ws = None

    async def connect(self) -> None:
        headers = {
            "Authorization": f"Bearer {self._client_secret}",
            "OpenAI-Beta": "realtime=v1",
        }
        try:
            self._ws = await websockets.connect(
                self._ws_url, additional_headers=headers
            )
        except TypeError:
            # websockets < 14 used `extra_headers`; the dependency range allows
            # both old and new releases.
            self._ws = await websockets.connect(self._ws_url, extra_headers=headers)

    async def send_audio(self, pcm16: bytes) -> None:
        if not pcm16 or self._ws is None:
            return
        await self._ws.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm16).decode("ascii"),
                }
            )
        )

    async def clear_audio(self) -> None:
        if self._ws is None:
            return
        await self._ws.send(json.dumps({"type": "input_audio_buffer.clear"}))

    async def events(self) -> AsyncIterator[dict]:
        if self._ws is None:
            raise RealtimeTranscriberError("transcriber is not connected")
        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if isinstance(data, dict):
                yield data

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
