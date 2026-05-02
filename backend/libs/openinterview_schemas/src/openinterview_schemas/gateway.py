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


# ---------- voice / delivery analysis ----------------------------------

class FillerCount(BaseModel):
    word: str
    count: int


class PronunciationIssue(BaseModel):
    word: str
    note: str | None = None


class VoiceTone(BaseModel):
    """Acoustic-style hints. All in [0,1] with simple monikers; the
    distinction is intentionally coarse so multiple providers can agree."""

    confidence: float | None = None
    energy: float | None = None
    monotone: float | None = None  # 0=expressive, 1=flat


class VoiceLanguageAccuracy(BaseModel):
    """Linguistic-correctness hints (grammar, idiom, word choice)."""

    score: float | None = None  # 0..1
    issues: list[str] = Field(default_factory=list)


class VoiceAnalysis(BaseModel):
    """Per-utterance breakdown returned by the gateway. Stored verbatim on
    the user-role chat message's ``meta.voice`` so downstream evaluators
    can aggregate it."""

    transcript: str
    duration_s: float | None = None
    wpm: float | None = None
    filler_words: list[FillerCount] = Field(default_factory=list)
    pause_count: int | None = None
    long_pauses_s: list[float] = Field(default_factory=list)
    tone: VoiceTone = Field(default_factory=VoiceTone)
    pronunciation_issues: list[PronunciationIssue] = Field(default_factory=list)
    language_accuracy: VoiceLanguageAccuracy = Field(
        default_factory=VoiceLanguageAccuracy
    )
    summary: str | None = None


class VoiceAnalysisRequest(BaseModel):
    user_id: UUID
    logical_model: str = Field(default="voice-analysis-default")
    audio_b64: str
    mime: str
    language: str | None = None
    transcript_hint: str | None = None  # if caller already transcribed


class VoiceAnalysisResponse(BaseModel):
    analysis: VoiceAnalysis
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
