"""Gateway domain service. Pure orchestration; no HTTP, no SQL."""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from openinterview_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    TokenUsage,
    TranscriptionRequest,
    TranscriptionResponse,
    VoiceAnalysis,
    VoiceAnalysisRequest,
    VoiceAnalysisResponse,
)

from .keys.interface import KeyResolver
from .providers.interface import LLMProvider, ProviderError
from .rate_limit.limiter import RateLimiter
from .rate_limit.tiers import TierCatalog
from .routing.catalog import ModelCatalog
from .usage.interface import UsageEvent, UsageRepository


def _ext_for_mime(mime: str) -> str:
    m = (mime or "").lower()
    if "webm" in m:
        return "webm"
    if "wav" in m:
        return "wav"
    if "ogg" in m or "opus" in m:
        return "ogg"
    if "mp3" in m or "mpeg" in m:
        return "mp3"
    if "mp4" in m or "m4a" in m:
        return "m4a"
    return "bin"


class GatewayError(Exception):
    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class TierLookup:
    """Resolves a user's tier name. Injected so tests can stub it."""

    fn: callable  # type: ignore[type-arg]  -- (UUID) -> str

    async def __call__(self, user_id: UUID) -> str:
        result = self.fn(user_id)
        if hasattr(result, "__await__"):
            return await result
        return result


class GatewayService:
    def __init__(
        self,
        *,
        catalog: ModelCatalog,
        keys: KeyResolver,
        provider: LLMProvider,
        limiter: RateLimiter,
        tiers: TierCatalog,
        usage: UsageRepository,
        tier_lookup: TierLookup,
    ) -> None:
        self._catalog = catalog
        self._keys = keys
        self._provider = provider
        self._limiter = limiter
        self._tiers = tiers
        self._usage = usage
        self._tier_lookup = tier_lookup

    async def chat(self, req: ChatCompletionRequest) -> ChatCompletionResponse:
        entry = self._catalog.resolve("chat", req.logical_model)
        creds = await self._keys.resolve(user_id=req.user_id, provider=entry.provider)
        if creds is None:
            raise GatewayError(
                f"no credentials for provider {entry.provider}", status=503
            )
        await self._enforce_rate_limit(user_id=req.user_id, mode=creds.mode)

        start = time.monotonic()
        status_code = 200
        error: str | None = None
        usage = TokenUsage()
        try:
            result = await self._provider.chat(
                endpoint=entry.endpoint,
                api_key=creds.api_key,
                model_id=entry.model_id,
                messages=req.messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                tools=req.tools,
                tool_choice=req.tool_choice,
            )
            usage = result.usage
            return ChatCompletionResponse(
                id=result.id,
                model=result.model,
                provider=entry.provider,
                content=result.content,
                tool_calls=result.tool_calls,
                usage=result.usage,
                finish_reason=result.finish_reason,
            )
        except ProviderError as e:
            status_code = e.status
            error = str(e)
            raise GatewayError(error, status=e.status) from e
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            await self._usage.record(
                UsageEvent(
                    user_id=req.user_id,
                    mode=creds.mode,
                    logical_model=entry.logical_name,
                    provider=entry.provider,
                    endpoint=entry.endpoint,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=status_code,
                    error=error,
                )
            )

    async def chat_stream(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[str]:
        entry = self._catalog.resolve("chat", req.logical_model)
        creds = await self._keys.resolve(user_id=req.user_id, provider=entry.provider)
        if creds is None:
            raise GatewayError(
                f"no credentials for provider {entry.provider}", status=503
            )
        await self._enforce_rate_limit(user_id=req.user_id, mode=creds.mode)

        if not hasattr(self._provider, "chat_stream"):
            # Provider doesn't support streaming -- fall back to non-streaming.
            resp = await self.chat(req)
            if resp.content:
                yield resp.content
            return

        start = time.monotonic()
        status_code = 200
        error: str | None = None
        total_chars = 0
        try:
            async for piece in self._provider.chat_stream(
                endpoint=entry.endpoint,
                api_key=creds.api_key,
                model_id=entry.model_id,
                messages=req.messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                tools=req.tools,
                tool_choice=req.tool_choice,
            ):
                total_chars += len(piece)
                yield piece
        except ProviderError as e:
            status_code = e.status
            error = str(e)
            raise GatewayError(error, status=e.status) from e
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            # Streaming responses don't carry token usage; record approximate counts.
            await self._usage.record(
                UsageEvent(
                    user_id=req.user_id,
                    mode=creds.mode,
                    logical_model=entry.logical_name,
                    provider=entry.provider,
                    endpoint=entry.endpoint,
                    usage=TokenUsage(
                        prompt_tokens=0,
                        completion_tokens=max(1, total_chars // 4),
                        total_tokens=max(1, total_chars // 4),
                    ),
                    latency_ms=latency_ms,
                    status=status_code,
                    error=error,
                )
            )

    async def embed(self, req: EmbeddingRequest) -> EmbeddingResponse:
        entry = self._catalog.resolve("embedding", req.logical_model)
        creds = await self._keys.resolve(user_id=req.user_id, provider=entry.provider)
        if creds is None:
            raise GatewayError(
                f"no credentials for provider {entry.provider}", status=503
            )
        await self._enforce_rate_limit(user_id=req.user_id, mode=creds.mode)

        start = time.monotonic()
        status_code = 200
        error: str | None = None
        usage = TokenUsage()
        try:
            result = await self._provider.embed(
                endpoint=entry.endpoint,
                api_key=creds.api_key,
                model_id=entry.model_id,
                inputs=req.inputs,
            )
            usage = result.usage
            return EmbeddingResponse(
                model=result.model,
                provider=entry.provider,
                vectors=result.vectors,
                usage=result.usage,
            )
        except ProviderError as e:
            status_code = e.status
            error = str(e)
            raise GatewayError(error, status=e.status) from e
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            await self._usage.record(
                UsageEvent(
                    user_id=req.user_id,
                    mode=creds.mode,
                    logical_model=entry.logical_name,
                    provider=entry.provider,
                    endpoint=entry.endpoint,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=status_code,
                    error=error,
                )
            )

    async def transcribe(self, req: TranscriptionRequest) -> TranscriptionResponse:
        import base64

        entry = self._catalog.resolve("transcription", req.logical_model)
        creds = await self._keys.resolve(user_id=req.user_id, provider=entry.provider)
        if creds is None:
            raise GatewayError(
                f"no credentials for provider {entry.provider}", status=503
            )
        await self._enforce_rate_limit(user_id=req.user_id, mode=creds.mode)

        try:
            audio = base64.b64decode(req.audio_b64)
        except Exception as e:  # noqa: BLE001
            raise GatewayError(f"invalid audio_b64: {e}", status=400) from e

        start = time.monotonic()
        status_code = 200
        error: str | None = None
        usage = TokenUsage()
        try:
            ext = _ext_for_mime(req.mime)
            result = await self._provider.transcribe(
                endpoint=entry.endpoint,
                api_key=creds.api_key,
                model_id=entry.model_id,
                audio=audio,
                mime=req.mime,
                filename=f"audio.{ext}",
                language=req.language,
            )
            usage = result.usage
            return TranscriptionResponse(
                text=result.text,
                model=result.model,
                provider=entry.provider,
                usage=result.usage,
            )
        except ProviderError as e:
            status_code = e.status
            error = str(e)
            raise GatewayError(error, status=e.status) from e
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            await self._usage.record(
                UsageEvent(
                    user_id=req.user_id,
                    mode=creds.mode,
                    logical_model=entry.logical_name,
                    provider=entry.provider,
                    endpoint=entry.endpoint,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=status_code,
                    error=error,
                )
            )

    async def analyze_voice(
        self, req: VoiceAnalysisRequest
    ) -> VoiceAnalysisResponse:
        """Audio-in delivery rubric.

        We resolve via the ``transcription`` model class so existing tier /
        usage plumbing applies to audio. The model id is whatever the catalog
        binds to the supplied logical name; in production callers wire
        ``voice-analysis-default`` to a multimodal-audio chat model
        (e.g. ``gpt-4o-audio-preview``).

        Fallback: if the logical model isn't configured, or the provider
        returns an error (most non-OpenAI backends don't accept
        ``input_audio`` yet), we transcribe the clip with the default STT
        model and ask the chat model to estimate delivery from the
        transcript alone (lower fidelity — no acoustic tone — but better
        than a 502).
        """
        import base64

        try:
            entry = self._catalog.resolve("transcription", req.logical_model)
        except KeyError:
            return await self._analyze_voice_fallback(req)
        creds = await self._keys.resolve(user_id=req.user_id, provider=entry.provider)
        if creds is None:
            raise GatewayError(
                f"no credentials for provider {entry.provider}", status=503
            )
        await self._enforce_rate_limit(user_id=req.user_id, mode=creds.mode)

        try:
            audio = base64.b64decode(req.audio_b64)
        except Exception as e:  # noqa: BLE001
            raise GatewayError(f"invalid audio_b64: {e}", status=400) from e

        start = time.monotonic()
        status_code = 200
        error: str | None = None
        usage = TokenUsage()
        try:
            try:
                result = await self._provider.analyze_voice(
                    endpoint=entry.endpoint,
                    api_key=creds.api_key,
                    model_id=entry.model_id,
                    audio=audio,
                    mime=req.mime,
                    transcript_hint=req.transcript_hint,
                    language=req.language,
                )
            except ProviderError:
                # The configured model probably doesn't accept input_audio.
                # Drop to the transcribe-then-score fallback so the caller
                # still gets a usable result.
                return await self._analyze_voice_fallback(req)
            usage = result.usage
            analysis = VoiceAnalysis.model_validate(result.analysis or {})
            return VoiceAnalysisResponse(
                analysis=analysis,
                model=result.model,
                provider=entry.provider,
                usage=result.usage,
            )
        except ProviderError as e:
            status_code = e.status
            error = str(e)
            raise GatewayError(error, status=e.status) from e
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            await self._usage.record(
                UsageEvent(
                    user_id=req.user_id,
                    mode=creds.mode,
                    logical_model=entry.logical_name,
                    provider=entry.provider,
                    endpoint=entry.endpoint,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=status_code,
                    error=error,
                )
            )

    async def _analyze_voice_fallback(
        self, req: VoiceAnalysisRequest
    ) -> VoiceAnalysisResponse:
        """STT → text-only delivery scoring.

        Used when the configured ``voice-analysis`` model is missing or
        doesn't support audio input. We transcribe the clip and ask a chat
        model to produce the same JSON shape from the transcript alone.
        Acoustic fields (tone, pause durations) come back null because we
        can't measure them from text — the rest is best-effort."""
        import base64
        import json as _json

        from openinterview_schemas import ChatMessage, TranscriptionRequest

        # 1) Transcribe.
        stt = await self.transcribe(
            TranscriptionRequest(
                user_id=req.user_id,
                logical_model="stt-default",
                audio_b64=req.audio_b64,
                mime=req.mime,
                language=req.language,
            )
        )
        transcript = (stt.text or "").strip()

        # 2) Score from text. Use a chat model to estimate delivery
        # *qualities* visible in writing (filler words, pace cues from
        # punctuation), and leave acoustic fields null.
        chat_entry = self._catalog.resolve("chat", "chat-fast")
        try:
            _chat_entry_default = self._catalog.resolve("chat", None)
        except KeyError:
            _chat_entry_default = chat_entry
        # Prefer the configured default; fall back to chat-fast.
        try:
            entry = self._catalog.resolve("chat", None)
        except KeyError:
            entry = chat_entry
        creds = await self._keys.resolve(
            user_id=req.user_id, provider=entry.provider
        )
        if creds is None:
            # No creds → return minimal transcript-only payload.
            return VoiceAnalysisResponse(
                analysis=VoiceAnalysis(transcript=transcript),
                model=stt.model,
                provider=stt.provider,
                usage=stt.usage,
            )

        prompt = (
            "You are an interview coach. Estimate delivery from this "
            "transcript only — you cannot hear the audio, so leave tone "
            "fields and long_pauses_s empty. Return STRICT JSON ONLY:\n"
            "{\n"
            '  "transcript": str,\n'
            '  "duration_s": null,\n'
            '  "wpm": null,\n'
            '  "filler_words": [{"word": str, "count": int}],\n'
            '  "pause_count": null,\n'
            '  "long_pauses_s": [],\n'
            '  "tone": {"confidence": null, "energy": null, "monotone": null},\n'
            '  "pronunciation_issues": [],\n'
            '  "language_accuracy": {"score": 0..1, "issues": [str]},\n'
            '  "summary": str\n'
            "}\n\n"
            f"TRANSCRIPT:\n{transcript[:4000]}"
        )
        analysis: dict = {"transcript": transcript}
        try:
            r = await self._provider.chat(
                endpoint=entry.endpoint,
                api_key=creds.api_key,
                model_id=entry.model_id,
                messages=[ChatMessage(role="user", content=prompt)],
                temperature=0,
            )
            try:
                parsed = _json.loads((r.content or "").strip())
                if isinstance(parsed, dict):
                    parsed.setdefault("transcript", transcript)
                    analysis = parsed
            except Exception:
                pass
        except ProviderError:
            pass
        # Estimate WPM from char count if model didn't fill it in
        # (rough but better than nothing — assumes ~5 chars/word).
        words = max(1, len(transcript.split()))
        if not analysis.get("wpm") and stt.text:
            # Without duration we can't compute true WPM; leave null.
            pass

        try:
            an = VoiceAnalysis.model_validate(analysis)
        except Exception:
            an = VoiceAnalysis(transcript=transcript)
        # Guarantee the transcript field is populated even if the LLM
        # decided to omit it.
        if not an.transcript:
            an = an.model_copy(update={"transcript": transcript})
        # Stash a hint so the agent prompt still flags this turn as audio.
        if an.summary is None:
            an = an.model_copy(
                update={
                    "summary": (
                        f"Audio response of ~{words} words "
                        "(text-only delivery estimate; acoustic features unavailable)."
                    )
                }
            )
        return VoiceAnalysisResponse(
            analysis=an,
            model=f"fallback:{stt.model}",
            provider=stt.provider,
            usage=stt.usage,
        )

    async def _enforce_rate_limit(self, *, user_id: UUID, mode: str) -> None:
        if mode == "byo":
            return  # BYO has no limits
        tier_name = await self._tier_lookup(user_id)
        tier = self._tiers.get(tier_name)
        key = f"{user_id}:{tier.name}"
        if not self._limiter.allow(key, tier.rate_limit_rpm):
            raise GatewayError("rate limit exceeded", status=429)
