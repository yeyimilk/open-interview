"""OpenAI-compatible HTTP client.

Works with OpenAI, Anthropic (via openai-compatible adapter), Ollama, vLLM,
LM Studio, Together, OpenRouter, and any service that speaks the OpenAI API.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from openinterview_schemas import ChatMessage, TokenUsage

from ...domain.providers.interface import (
    EmbeddingResult,
    LLMProvider,
    ProviderError,
    ProviderResult,
)


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, *, timeout_s: float = 60.0, client: httpx.AsyncClient | None = None) -> None:
        self._timeout = timeout_s
        self._client = client  # injectable for tests

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def _post(self, endpoint: str, path: str, api_key: str, body: dict) -> dict:
        url = endpoint.rstrip("/") + path
        if self._client is not None:
            r = await self._client.post(url, headers=self._headers(api_key), json=body)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.post(url, headers=self._headers(api_key), json=body)
        if r.status_code >= 400:
            raise ProviderError(
                f"upstream {r.status_code}: {r.text[:500]}", status=502
            )
        return r.json()

    async def chat(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResult:
        body: dict = {
            "model": model_id,
            "messages": [m.model_dump() for m in messages],
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        data = await self._post(endpoint, "/chat/completions", api_key, body)
        return _parse_chat(data, model_id)

    async def embed(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        inputs: list[str],
    ) -> EmbeddingResult:
        body = {"model": model_id, "input": inputs}
        data = await self._post(endpoint, "/embeddings", api_key, body)
        return _parse_embeddings(data, model_id)

    async def chat_stream(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        body: dict = {
            "model": model_id,
            "messages": [m.model_dump() for m in messages],
            "stream": True,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        url = endpoint.rstrip("/") + "/chat/completions"
        headers = self._headers(api_key)

        async def _consume(client: httpx.AsyncClient) -> AsyncIterator[str]:
            async with client.stream("POST", url, headers=headers, json=body) as r:
                if r.status_code >= 400:
                    txt = await r.aread()
                    raise ProviderError(
                        f"upstream {r.status_code}: {txt.decode(errors='ignore')[:500]}",
                        status=502,
                    )
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            return
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        try:
                            choice = obj["choices"][0]
                        except (KeyError, IndexError, TypeError):
                            continue
                        delta = choice.get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            yield piece

        if self._client is not None:
            async for piece in _consume(self._client):
                yield piece
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                async for piece in _consume(c):
                    yield piece


def _parse_chat(data: dict, model_id: str) -> ProviderResult:
    try:
        choice = data["choices"][0]
        msg = choice["message"]["content"]
        finish = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"malformed chat response: {e}") from e
    usage = data.get("usage") or {}
    return ProviderResult(
        id=str(data.get("id", "")),
        model=str(data.get("model", model_id)),
        content=msg or "",
        usage=TokenUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
        ),
        finish_reason=finish,
    )


def _parse_embeddings(data: dict, model_id: str) -> EmbeddingResult:
    try:
        items = data["data"]
        vectors = [list(map(float, it["embedding"])) for it in items]
    except (KeyError, TypeError) as e:
        raise ProviderError(f"malformed embedding response: {e}") from e
    usage = data.get("usage") or {}
    return EmbeddingResult(
        model=str(data.get("model", model_id)),
        vectors=vectors,
        usage=TokenUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
        ),
    )
