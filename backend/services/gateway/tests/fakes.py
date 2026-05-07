"""Test doubles for provider isolation."""
from __future__ import annotations

from openinterview_schemas import ChatMessage, TokenUsage

from openinterview_gateway.domain.providers.interface import (
    EmbeddingResult,
    LLMProvider,
    ProviderResult,
    RealtimeTranscriptionSessionResult,
    TranscriptionResult,
)


class FakeProvider(LLMProvider):
    def __init__(self) -> None:
        self.chat_calls: list[dict] = []
        self.embed_calls: list[dict] = []
        self.transcribe_calls: list[dict] = []
        self.realtime_session_calls: list[dict] = []

    async def chat(  # type: ignore[override]
        self,
        *,
        endpoint,
        api_key,
        model_id,
        messages,
        temperature=None,
        max_tokens=None,
        tools=None,
        tool_choice=None,
    ):
        self.chat_calls.append(
            {
                "endpoint": endpoint,
                "api_key": api_key,
                "model_id": model_id,
                "n_messages": len(messages),
                "tools": tools,
            }
        )
        return ProviderResult(
            id="fake-1",
            model=model_id,
            content=f"echo:{messages[-1].content}",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    async def embed(self, *, endpoint, api_key, model_id, inputs):  # type: ignore[override]
        self.embed_calls.append(
            {"endpoint": endpoint, "api_key": api_key, "model_id": model_id, "n": len(inputs)}
        )
        return EmbeddingResult(
            model=model_id,
            vectors=[[0.1, 0.2, 0.3] for _ in inputs],
            usage=TokenUsage(prompt_tokens=len(inputs), total_tokens=len(inputs)),
        )

    async def transcribe(  # type: ignore[override]
        self,
        *,
        endpoint,
        api_key,
        model_id,
        audio,
        mime,
        filename="audio.bin",
        language=None,
    ):
        self.transcribe_calls.append(
            {
                "endpoint": endpoint,
                "model_id": model_id,
                "mime": mime,
                "filename": filename,
                "language": language,
                "size": len(audio),
            }
        )
        return TranscriptionResult(
            model=model_id,
            text=f"transcribed:{len(audio)}",
            usage=TokenUsage(),
        )

    async def create_realtime_transcription_session(  # type: ignore[override]
        self,
        *,
        endpoint,
        api_key,
        model_id,
        language=None,
        prompt="",
        noise_reduction="near_field",
        turn_detection="semantic_vad",
        vad_eagerness="medium",
        include_logprobs=True,
    ):
        self.realtime_session_calls.append(
            {
                "endpoint": endpoint,
                "api_key": api_key,
                "model_id": model_id,
                "language": language,
                "prompt": prompt,
                "noise_reduction": noise_reduction,
                "turn_detection": turn_detection,
                "vad_eagerness": vad_eagerness,
                "include_logprobs": include_logprobs,
            }
        )
        return RealtimeTranscriptionSessionResult(
            model=model_id,
            client_secret="ek_test_ephemeral",
            expires_at=1234567890,
            session_id="sess_test",
            ws_url="wss://api.openai.com/v1/realtime?intent=transcription",
        )
