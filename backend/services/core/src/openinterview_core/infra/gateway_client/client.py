"""HTTP client to the GenAI Gateway. The only place core/workers talk to LLMs."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import httpx

import base64

from openinterview_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    EmbeddingRequest,
    EmbeddingResponse,
    ToolDefinition,
    TranscriptionRequest,
    TranscriptionResponse,
)


class GatewayClientError(Exception):
    def __init__(self, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class GatewayClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = service_token
        self._timeout = timeout_s
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def _post(self, path: str, body: dict) -> dict:
        url = f"{self._base}{path}"
        if self._client is not None:
            r = await self._client.post(url, headers=self._headers(), json=body)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.post(url, headers=self._headers(), json=body)
        if r.status_code >= 400:
            raise GatewayClientError(
                f"gateway {r.status_code}: {r.text[:500]}", status=r.status_code
            )
        return r.json()

    async def chat(
        self,
        *,
        user_id: UUID,
        logical_model: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[ToolDefinition] | None = None,
        tool_choice: str | dict | None = None,
    ) -> ChatCompletionResponse:
        req = ChatCompletionRequest(
            user_id=user_id,
            logical_model=logical_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        data = await self._post("/v1/chat/completions", req.model_dump(mode="json"))
        return ChatCompletionResponse.model_validate(data)

    async def transcribe(
        self,
        *,
        user_id: UUID,
        logical_model: str,
        audio: bytes,
        mime: str,
        language: str | None = None,
    ) -> TranscriptionResponse:
        req = TranscriptionRequest(
            user_id=user_id,
            logical_model=logical_model,
            audio_b64=base64.b64encode(audio).decode("ascii"),
            mime=mime,
            language=language,
        )
        data = await self._post(
            "/v1/audio/transcribe", req.model_dump(mode="json")
        )
        return TranscriptionResponse.model_validate(data)

    async def embed(
        self,
        *,
        user_id: UUID,
        logical_model: str,
        inputs: list[str],
    ) -> EmbeddingResponse:
        req = EmbeddingRequest(
            user_id=user_id, logical_model=logical_model, inputs=inputs
        )
        data = await self._post("/v1/embeddings", req.model_dump(mode="json"))
        return EmbeddingResponse.model_validate(data)

    async def chat_stream(
        self,
        *,
        user_id: UUID,
        logical_model: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[ToolDefinition] | None = None,
        tool_choice: str | dict | None = None,
    ) -> AsyncIterator[str]:
        """Yields content deltas (str) from the gateway's streaming endpoint.

        Falls back to non-streaming /chat/completions if the gateway returns
        a non-SSE response (e.g., older deployment).
        """
        req = ChatCompletionRequest(
            user_id=user_id,
            logical_model=logical_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        url = f"{self._base}/v1/chat/completions/stream"
        body = req.model_dump(mode="json")
        emitted = False

        async def _consume(client: httpx.AsyncClient) -> AsyncIterator[str]:
            nonlocal emitted
            async with client.stream(
                "POST", url, headers=self._headers(), json=body
            ) as r:
                if r.status_code == 404:
                    # gateway has no stream endpoint -- fall back below
                    return
                if r.status_code >= 400:
                    txt = await r.aread()
                    raise GatewayClientError(
                        f"gateway {r.status_code}: {txt.decode(errors='ignore')[:500]}",
                        status=r.status_code,
                    )
                buf = ""
                async for chunk in r.aiter_text():
                    buf += chunk
                    while "\n\n" in buf:
                        block, buf = buf.split("\n\n", 1)
                        ev = _parse_sse_block(block)
                        if ev is None:
                            continue
                        name, payload = ev
                        if name == "delta":
                            piece = payload.get("content", "") if isinstance(payload, dict) else ""
                            if piece:
                                emitted = True
                                yield piece
                        elif name == "done":
                            return
                        elif name == "error":
                            msg = (
                                payload.get("message")
                                if isinstance(payload, dict)
                                else "stream error"
                            )
                            raise GatewayClientError(
                                f"gateway stream error: {msg}", status=502
                            )

        try:
            if self._client is not None:
                async for piece in _consume(self._client):
                    yield piece
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as c:
                    async for piece in _consume(c):
                        yield piece
        except GatewayClientError:
            raise
        if emitted:
            return

        # Fallback: non-streaming
        resp = await self.chat(
            user_id=user_id,
            logical_model=logical_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if resp.content:
            yield resp.content


def _parse_sse_block(block: str) -> tuple[str, object] | None:
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
        return name, json.loads(data)
    except Exception:
        return name, data
