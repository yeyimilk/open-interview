"""DTOs for the GenAI Gateway service. OpenAI-shaped where applicable."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: dict[str, Any]  # {name: str, arguments: str (JSON-encoded)}


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolDefinition(BaseModel):
    type: Literal["function"] = "function"
    function: dict[str, Any]  # {name, description, parameters: JSON-Schema}


class ChatCompletionRequest(BaseModel):
    user_id: UUID
    logical_model: str = Field(..., description="Logical model name (see models.yaml)")
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tools: list[ToolDefinition] | None = None
    tool_choice: str | dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    model: str
    provider: str
    content: str
    tool_calls: list[ToolCall] | None = None
    usage: TokenUsage
    finish_reason: str | None = None


class TranscriptionRequest(BaseModel):
    user_id: UUID
    logical_model: str = Field(default="stt-default")
    audio_b64: str
    mime: str
    language: str | None = None


class TranscriptionResponse(BaseModel):
    text: str
    model: str
    provider: str
    usage: TokenUsage = Field(default_factory=TokenUsage)


class EmbeddingRequest(BaseModel):
    user_id: UUID
    logical_model: str
    inputs: list[str]


class EmbeddingResponse(BaseModel):
    model: str
    provider: str
    vectors: list[list[float]]
    usage: TokenUsage


class UsageRecord(BaseModel):
    id: UUID
    user_id: UUID
    mode: Literal["byo", "shared"]
    logical_model: str
    provider: str
    endpoint: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    status: int
    error: str | None = None
    created_at: datetime
