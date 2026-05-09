"""HTTP client to the GenAI Gateway. The only place core/workers talk to LLMs."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

import httpx

from openinterview_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    EmbeddingRequest,
    EmbeddingResponse,
    ProviderModelList,
    ProviderOverride,
    ProviderTestRequest,
    ProviderTestResponse,
    ToolDefinition,
    TranscriptionRequest,
    TranscriptionResponse,
    VoiceAnalysisRequest,
    VoiceAnalysisResponse,
)
from openinterview_logging import get_logger

# (user_id, role) -> ProviderOverride | None. The role is one of "chat",
# "embedding", "transcription", "voice-analysis". The resolver is awaited
# once per gateway request; it should return None when there's no per-user
# override.
OverrideResolver = Callable[[UUID, str], Awaitable["ProviderOverride | None"]]
log = get_logger(__name__)


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
        override_resolver: OverrideResolver | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = service_token
        self._timeout = timeout_s
        self._client = client
        self._override_resolver = override_resolver

    async def _resolve_override(
        self, user_id: UUID, role: str
    ) -> ProviderOverride | None:
        if self._override_resolver is None:
            return None
        try:
            return await self._override_resolver(user_id, role)
        except Exception:
            # Pref lookup must never break gateway calls.
            return None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def _post(self, path: str, body: dict, *, operation: str = "gateway_post") -> dict:
        url = f"{self._base}{path}"
        started = time.perf_counter()
        user_hash = _hash_id(body.get("user_id"))
        logical_model = body.get("logical_model")
        status = 0
        try:
            if self._client is not None:
                r = await self._client.post(url, headers=self._headers(), json=body)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as c:
                    r = await c.post(url, headers=self._headers(), json=body)
            status = r.status_code
            if r.status_code >= 400:
                raise GatewayClientError(
                    f"gateway {r.status_code}: {r.text[:500]}", status=r.status_code
                )
            return r.json()
        except Exception as e:
            log.warning(
                "gateway_request_failed",
                operation=operation,
                path=path,
                status=status,
                user_hash=user_hash,
                logical_model=logical_model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=str(e),
            )
            raise
        finally:
            if status and status < 400:
                log.info(
                    "gateway_request",
                    operation=operation,
                    path=path,
                    status=status,
                    user_hash=user_hash,
                    logical_model=logical_model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )

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
            override=await self._resolve_override(user_id, "chat"),
        )
        data = await self._post(
            "/v1/chat/completions",
            req.model_dump(mode="json"),
            operation="chat",
        )
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
            override=await self._resolve_override(user_id, "transcription"),
        )
        data = await self._post(
            "/v1/audio/transcribe",
            req.model_dump(mode="json"),
            operation="transcribe",
        )
        return TranscriptionResponse.model_validate(data)

    async def analyze_voice(
        self,
        *,
        user_id: UUID,
        logical_model: str = "voice-analysis-default",
        audio: bytes,
        mime: str,
        language: str | None = None,
        transcript_hint: str | None = None,
    ) -> VoiceAnalysisResponse:
        req = VoiceAnalysisRequest(
            user_id=user_id,
            logical_model=logical_model,
            audio_b64=base64.b64encode(audio).decode("ascii"),
            mime=mime,
            language=language,
            transcript_hint=transcript_hint,
            override=await self._resolve_override(user_id, "voice-analysis"),
        )
        data = await self._post(
            "/v1/audio/analyze",
            req.model_dump(mode="json"),
            operation="analyze_voice",
        )
        return VoiceAnalysisResponse.model_validate(data)

    async def embed(
        self,
        *,
        user_id: UUID,
        logical_model: str,
        inputs: list[str],
    ) -> EmbeddingResponse:
        req = EmbeddingRequest(
            user_id=user_id,
            logical_model=logical_model,
            inputs=inputs,
            override=await self._resolve_override(user_id, "embedding"),
        )
        data = await self._post(
            "/v1/embeddings",
            req.model_dump(mode="json"),
            operation="embed",
        )
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
            override=await self._resolve_override(user_id, "chat"),
        )
        url = f"{self._base}/v1/chat/completions/stream"
        body = req.model_dump(mode="json")
        started = time.perf_counter()
        user_hash = _hash_id(user_id)
        status = 0
        emitted = False

        async def _consume(client: httpx.AsyncClient) -> AsyncIterator[str]:
            nonlocal emitted, status
            async with client.stream(
                "POST", url, headers=self._headers(), json=body
            ) as r:
                status = r.status_code
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
        except Exception as e:
            log.warning(
                "gateway_stream_failed",
                operation="chat_stream",
                path="/v1/chat/completions/stream",
                status=getattr(e, "status", status),
                user_hash=user_hash,
                logical_model=logical_model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=str(e),
            )
            raise
        if emitted:
            log.info(
                "gateway_stream",
                operation="chat_stream",
                path="/v1/chat/completions/stream",
                status=status,
                user_hash=user_hash,
                logical_model=logical_model,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
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

    async def list_provider_models(
        self, *, user_id: UUID, provider: str, endpoint: str
    ) -> ProviderModelList:
        url = (
            f"{self._base}/v1/providers/{provider}/models"
            f"?user_id={user_id}&endpoint={endpoint}"
        )
        if self._client is not None:
            r = await self._client.get(url, headers=self._headers())
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.get(url, headers=self._headers())
        if r.status_code >= 400:
            raise GatewayClientError(
                f"gateway {r.status_code}: {r.text[:500]}", status=r.status_code
            )
        return ProviderModelList.model_validate(r.json())

    async def test_provider(
        self,
        *,
        user_id: UUID,
        role: str,
        provider: str,
        endpoint: str,
        model_id: str,
    ) -> ProviderTestResponse:
        req = ProviderTestRequest(
            user_id=user_id,
            role=role,  # type: ignore[arg-type]
            provider=provider,
            endpoint=endpoint,
            model_id=model_id,
        )
        data = await self._post(
            "/v1/providers/test",
            req.model_dump(mode="json"),
            operation="test_provider",
        )
        return ProviderTestResponse.model_validate(data)


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


def _hash_id(value: object) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(str(value).encode()).hexdigest()[:10]
