"""Provider interface. Domain depends on this; concrete clients live in infra."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from openinterview_schemas import ChatMessage, TokenUsage


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ProviderResult:
    id: str
    model: str
    content: str
    usage: TokenUsage
    finish_reason: str | None


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    vectors: list[list[float]]
    usage: TokenUsage


class LLMProvider(Protocol):
    async def chat(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResult: ...

    async def embed(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        inputs: list[str],
    ) -> EmbeddingResult: ...

    def chat_stream(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        messages: list[ChatMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...
