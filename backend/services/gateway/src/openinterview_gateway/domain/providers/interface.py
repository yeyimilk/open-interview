"""Provider interface. Domain depends on this; concrete clients live in infra."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from openinterview_schemas import ChatMessage, ToolCall, ToolDefinition, TokenUsage


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
    tool_calls: list[ToolCall] | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    vectors: list[list[float]]
    usage: TokenUsage


@dataclass(frozen=True)
class TranscriptionResult:
    model: str
    text: str
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
        tools: list[ToolDefinition] | None = None,
        tool_choice: str | dict | None = None,
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
        tools: list[ToolDefinition] | None = None,
        tool_choice: str | dict | None = None,
    ) -> AsyncIterator[str]: ...

    async def transcribe(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        audio: bytes,
        mime: str,
        filename: str = "audio.webm",
        language: str | None = None,
    ) -> TranscriptionResult: ...
