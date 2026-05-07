"""OpenAI-compatible HTTP client.

Works with OpenAI, Anthropic (via openai-compatible adapter), Ollama, vLLM,
LM Studio, Together, OpenRouter, and any service that speaks the OpenAI API.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from openinterview_schemas import ChatMessage, ToolCall, ToolDefinition, TokenUsage

from ...domain.providers.interface import (
    EmbeddingResult,
    LLMProvider,
    ProviderError,
    ProviderModelInfo,
    ProviderResult,
    RealtimeTranscriptionSessionResult,
    TranscriptionResult,
    VoiceAnalysisResult,
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
        tools: list[ToolDefinition] | None = None,
        tool_choice: str | dict | None = None,
    ) -> ProviderResult:
        body: dict = {
            "model": model_id,
            "messages": [_msg_to_wire(m) for m in messages],
        }
        _apply_sampling(body, model_id, temperature, max_tokens)
        if tools:
            body["tools"] = [t.model_dump() for t in tools]
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        try:
            data = await self._post(endpoint, "/chat/completions", api_key, body)
        except ProviderError as e:
            retried = _retry_body_for_param_error(body, str(e))
            if retried is None:
                raise
            data = await self._post(endpoint, "/chat/completions", api_key, retried)
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
        tools: list[ToolDefinition] | None = None,
        tool_choice: str | dict | None = None,
    ) -> AsyncIterator[str]:
        body: dict = {
            "model": model_id,
            "messages": [_msg_to_wire(m) for m in messages],
            "stream": True,
        }
        _apply_sampling(body, model_id, temperature, max_tokens)
        if tools:
            body["tools"] = [t.model_dump() for t in tools]
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        url = endpoint.rstrip("/") + "/chat/completions"
        headers = self._headers(api_key)

        async def _consume(
            client: httpx.AsyncClient, current_body: dict
        ) -> AsyncIterator[str]:
            async with client.stream(
                "POST", url, headers=headers, json=current_body
            ) as r:
                if r.status_code >= 400:
                    txt = await r.aread()
                    msg = txt.decode(errors="ignore")[:500]
                    retried = _retry_body_for_param_error(current_body, msg)
                    if retried is not None:
                        async for piece in _consume(client, retried):
                            yield piece
                        return
                    raise ProviderError(
                        f"upstream {r.status_code}: {msg}",
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
            async for piece in _consume(self._client, body):
                yield piece
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                async for piece in _consume(c, body):
                    yield piece


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
    ) -> TranscriptionResult:
        url = endpoint.rstrip("/") + "/audio/transcriptions"
        files = {"file": (filename, audio, mime or "application/octet-stream")}
        form: dict[str, str] = {"model": model_id, "response_format": "json"}
        if language:
            form["language"] = language
        headers = {"Authorization": f"Bearer {api_key}"}
        if self._client is not None:
            r = await self._client.post(url, headers=headers, data=form, files=files)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.post(url, headers=headers, data=form, files=files)
        if r.status_code >= 400:
            raise ProviderError(
                f"upstream {r.status_code}: {r.text[:500]}", status=502
            )
        try:
            data = r.json()
            text = data.get("text", "")
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"malformed transcription response: {e}") from e
        return TranscriptionResult(
            model=model_id,
            text=text,
            usage=TokenUsage(),
        )

    async def create_realtime_transcription_session(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        language: str | None = None,
        prompt: str = "",
        noise_reduction: str | None = "near_field",
        turn_detection: str = "semantic_vad",
        vad_eagerness: str = "low",
        include_logprobs: bool = True,
    ) -> RealtimeTranscriptionSessionResult:
        body: dict = {
            "input_audio_format": "pcm16",
            "input_audio_transcription": {
                "model": model_id,
                "prompt": prompt or "",
            },
            "turn_detection": _realtime_turn_detection(
                turn_detection=turn_detection,
                vad_eagerness=vad_eagerness,
            ),
        }
        if language:
            body["input_audio_transcription"]["language"] = language
        body["input_audio_noise_reduction"] = (
            None if noise_reduction is None else {"type": noise_reduction}
        )
        if include_logprobs:
            body["include"] = ["item.input_audio_transcription.logprobs"]

        data = await self._post(
            endpoint, "/realtime/transcription_sessions", api_key, body
        )
        secret = data.get("client_secret") or {}
        value = secret.get("value")
        if not isinstance(value, str) or not value:
            raise ProviderError("malformed realtime transcription session response")
        return RealtimeTranscriptionSessionResult(
            model=model_id,
            client_secret=value,
            expires_at=secret.get("expires_at"),
            session_id=data.get("id"),
            ws_url="wss://api.openai.com/v1/realtime?intent=transcription",
        )

    async def analyze_voice(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_id: str,
        audio: bytes,
        mime: str,
        transcript_hint: str | None = None,
        language: str | None = None,
    ) -> VoiceAnalysisResult:
        """Audio-in delivery analysis.

        Strategy: send the audio as an inline ``input_audio`` message part
        to OpenAI-compatible chat completions and ask for STRICT JSON. This
        works against any backend that supports the audio multimodal input
        on ``chat.completions`` (gpt-4o-audio-preview, gpt-4o-mini-audio,
        Gemini compat shims, etc.). Providers without audio-in will return
        an HTTP error which the caller surfaces; the service-level wrapper
        falls back to a transcribe-then-analyse path.
        """
        import base64 as _b64

        b64 = _b64.b64encode(audio).decode("ascii")
        # Best-effort format hint; OpenAI accepts wav, mp3, webm, ogg, m4a.
        fmt = "wav"
        if "/" in (mime or ""):
            fmt = (mime or "").split("/", 1)[1].split(";", 1)[0].strip()
        prompt = _voice_analysis_prompt(transcript_hint=transcript_hint, language=language)
        body = {
            "model": model_id,
            "modalities": ["text"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": b64, "format": fmt},
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        data = await self._post(endpoint, "/chat/completions", api_key, body)
        try:
            choice = data["choices"][0]["message"]["content"] or "{}"
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"malformed voice-analysis response: {e}") from e
        analysis = _safe_json(choice, default={}) or {}
        usage = data.get("usage") or {}
        return VoiceAnalysisResult(
            model=str(data.get("model", model_id)),
            analysis=analysis,
            usage=TokenUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
            ),
        )


    async def list_models(
        self, *, endpoint: str, api_key: str
    ) -> list[ProviderModelInfo]:
        """List available models via OpenAI-style ``GET /v1/models``.

        Works with OpenAI, OpenRouter, Together, Fireworks, vLLM, Ollama
        and LM Studio. Returns an empty list for providers that don't
        expose this endpoint (caller falls back to a static suggestion)."""
        url = endpoint.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        if self._client is not None:
            r = await self._client.get(url, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.get(url, headers=headers)
        if r.status_code >= 400:
            raise ProviderError(
                f"upstream {r.status_code}: {r.text[:500]}", status=r.status_code
            )
        try:
            data = r.json()
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"malformed models response: {e}") from e
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        out: list[ProviderModelInfo] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            mid = str(row.get("id") or "").strip()
            if not mid:
                continue
            owned = row.get("owned_by")
            created = row.get("created")
            out.append(
                ProviderModelInfo(
                    id=mid,
                    owned_by=str(owned) if owned else None,
                    created=int(created) if isinstance(created, (int, float)) else None,
                )
            )
        return out


def _voice_analysis_prompt(
    *, transcript_hint: str | None, language: str | None
) -> str:
    hint = (
        f"\nThe candidate said (best-effort transcript hint): {transcript_hint}\n"
        if transcript_hint
        else ""
    )
    lang = f"\nLanguage: {language}" if language else ""
    return (
        "You are an interview coach analysing a candidate's answer recording. "
        "Listen carefully and produce STRICT JSON ONLY (no prose) with this shape:\n"
        "{\n"
        '  "transcript": str,                          // verbatim, with punctuation\n'
        '  "duration_s": number,\n'
        '  "wpm": number,\n'
        '  "filler_words": [{"word": str, "count": int}],\n'
        '  "pause_count": int,\n'
        '  "long_pauses_s": [number],                  // seconds, only for pauses >= 1.5s\n'
        '  "tone": {"confidence": 0..1, "energy": 0..1, "monotone": 0..1},\n'
        '  "pronunciation_issues": [{"word": str, "note": str}],\n'
        '  "language_accuracy": {"score": 0..1, "issues": [str]},\n'
        '  "summary": str                              // 1-2 sentences on delivery\n'
        "}\n"
        "Be objective and concise. Empty arrays / null fields are fine when "
        "the recording is too short or noisy to judge a metric." + lang + hint
    )


def _safe_json(text: str, *, default):
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return json.loads(cleaned)
    except Exception:
        return default


def _realtime_turn_detection(*, turn_detection: str, vad_eagerness: str) -> dict:
    if turn_detection == "semantic_vad":
        return {
            "type": "semantic_vad",
            "eagerness": vad_eagerness or "low",
        }
    return {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 500,
    }


_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _is_reasoning_model(model_id: str) -> bool:
    """OpenAI's reasoning models (o-series, gpt-5) reject ``max_tokens`` and
    non-default ``temperature``. Detect by the canonical id prefix; matches
    work for ``o1``, ``o1-mini``, ``o3-mini``, ``o4-mini``, ``gpt-5``,
    ``openai/gpt-5`` (OpenRouter), etc."""
    mid = (model_id or "").lower()
    # strip provider prefixes like "openai/" or "vendor:"
    for sep in ("/", ":"):
        if sep in mid:
            mid = mid.split(sep, 1)[1]
    return mid.startswith(_REASONING_PREFIXES)


_REASONING_MIN_COMPLETION_TOKENS = 16000


def _apply_sampling(
    body: dict,
    model_id: str,
    temperature: float | None,
    max_tokens: int | None,
) -> None:
    """Set temperature + max_tokens on the request body, picking the
    parameter name expected by the model family. Reasoning models use
    ``max_completion_tokens`` and silently drop a non-default temperature.
    Reasoning tokens count against the limit *before* any visible content,
    so we floor the budget high enough that small caller hints (e.g. 256)
    don't get fully consumed by hidden reasoning."""
    if _is_reasoning_model(model_id):
        budget = max_tokens if max_tokens is not None else _REASONING_MIN_COMPLETION_TOKENS
        if budget < _REASONING_MIN_COMPLETION_TOKENS:
            budget = _REASONING_MIN_COMPLETION_TOKENS
        body["max_completion_tokens"] = budget
        # reasoning models only accept the default temperature; skip it
        return
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens


def _retry_body_for_param_error(body: dict, msg: str) -> dict | None:
    """When the upstream rejects a known parameter, build a one-shot retry
    body. Returns ``None`` when the error is unrecoverable so the caller
    re-raises."""
    low = msg.lower()
    new = dict(body)
    changed = False
    if "max_tokens" in low and "max_completion_tokens" in low:
        if "max_tokens" in new:
            new["max_completion_tokens"] = new.pop("max_tokens")
            changed = True
    if "temperature" in low and (
        "unsupported" in low or "does not support" in low
    ):
        if "temperature" in new:
            new.pop("temperature")
            changed = True
    # Reasoning model burned through the budget on hidden reasoning tokens
    # before producing visible output. Bump and retry once.
    if "output limit was reached" in low or (
        "max_tokens" in low and "higher" in low
    ):
        for k in ("max_completion_tokens", "max_tokens"):
            if k in new:
                cur = int(new[k] or 0)
                bumped = max(cur * 2, 32000)
                if bumped > cur:
                    new[k] = bumped
                    changed = True
                    break
        else:
            # No budget in the body at all — explicitly set a generous one.
            new["max_completion_tokens"] = 32000
            changed = True
    return new if changed else None


def _msg_to_wire(m: ChatMessage) -> dict:
    """Map our ChatMessage to OpenAI's wire format, omitting null fields."""
    out: dict = {"role": m.role, "content": m.content or ""}
    if m.name:
        out["name"] = m.name
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    if m.tool_calls:
        out["tool_calls"] = [tc.model_dump() for tc in m.tool_calls]
    return out


def _parse_chat(data: dict, model_id: str) -> ProviderResult:
    try:
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content") or ""
        finish = choice.get("finish_reason")
        raw_tool_calls = msg.get("tool_calls") or []
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"malformed chat response: {e}") from e
    tool_calls = None
    if raw_tool_calls:
        tool_calls = [
            ToolCall(
                id=str(tc.get("id", "")),
                type="function",
                function=tc.get("function") or {},
            )
            for tc in raw_tool_calls
        ]
    usage = data.get("usage") or {}
    return ProviderResult(
        id=str(data.get("id", "")),
        model=str(data.get("model", model_id)),
        content=content,
        tool_calls=tool_calls,
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
