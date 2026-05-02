"""Audio-mode interviewer turn: posts a multipart audio upload, asserts the
gateway's analyze_voice() is called, the user message is persisted with
voice meta, the per-turn evaluator sees delivery features, and the final
session evaluation surfaces a delivery_score."""
from __future__ import annotations

import json
import os
import struct
import uuid

import pytest

pytest.importorskip("aiosqlite")

from httpx import ASGITransport, AsyncClient

from openinterview_core.app import create_app
from openinterview_core.config import Settings
from openinterview_core.infra.vector import InMemoryVectorStore
from openinterview_schemas import (
    ChatCompletionResponse,
    EmbeddingResponse,
    TokenUsage,
    VoiceAnalysis,
    VoiceAnalysisResponse,
    VoiceLanguageAccuracy,
    VoiceTone,
)


def _resp(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="x",
        model="m",
        provider="p",
        content=content,
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
    )


class FakeAudioGateway:
    """Captures analyze_voice calls and returns canned voice metrics +
    canned chat responses for the per-turn / session evaluators."""

    def __init__(self) -> None:
        self.analyze_calls: list[dict] = []
        self.last_eval_prompt: str = ""
        self.eval_prompts: list[str] = []
        self.last_session_prompt: str = ""

    async def analyze_voice(
        self,
        *,
        user_id,
        audio: bytes,
        mime: str,
        language: str | None = None,
        transcript_hint: str | None = None,
        logical_model: str = "voice-analysis-default",
    ) -> VoiceAnalysisResponse:
        self.analyze_calls.append(
            {"size": len(audio), "mime": mime, "lang": language}
        )
        return VoiceAnalysisResponse(
            analysis=VoiceAnalysis(
                transcript="We use FastAPI with um async workers.",
                duration_s=12.5,
                wpm=125,
                filler_words=[{"word": "um", "count": 3}],
                pause_count=2,
                long_pauses_s=[1.8],
                tone=VoiceTone(confidence=0.7, energy=0.6, monotone=0.4),
                language_accuracy=VoiceLanguageAccuracy(score=0.9, issues=[]),
                summary="Calm, mid-pace delivery with a few fillers.",
            ),
            model="voice-x",
            provider="fake",
        )

    async def chat(self, *, user_id, logical_model, messages, **kwargs):
        prompt = messages[-1].content if messages else ""
        if "evaluating a candidate" in prompt.lower():
            self.last_eval_prompt = prompt
            self.eval_prompts.append(prompt)
            payload = {
                "score": 4,
                "feedback": "Solid.",
                "missed_points": [],
                "probe_question": None,
            }
            if "DELIVERY METRICS" in prompt:
                payload["delivery_score"] = 4
                payload["delivery_feedback"] = "good pace, watch fillers"
            return _resp(json.dumps(payload))
        if "interview panel chair" in prompt.lower():
            self.last_session_prompt = prompt
            payload = {
                "overall_score": 4.0,
                "scores": {"architecture": 4.0},
                "summary": "Strong content, decent delivery.",
                "strengths": ["clear FastAPI knowledge"],
                "weaknesses": ["fillers"],
                "suggested_practice": [
                    {"area": "speaking", "why": "fillers", "next_step": "record drills"},
                ],
            }
            if "DELIVERY METRICS" in prompt:
                payload["delivery_score"] = 4.2
                payload["delivery_feedback"] = [
                    {"area": "fillers", "note": "reduce 'um' usage"},
                ]
            return _resp(json.dumps(payload))
        if "distilling" in prompt.lower():
            return _resp(json.dumps({"episodic_summary": "", "long_term": []}))
        return _resp("Next question: tell me about scaling.")

    async def chat_stream(self, *, user_id, logical_model, messages, **kwargs):
        r = await self.chat(
            user_id=user_id, logical_model=logical_model, messages=messages
        )
        for i in range(0, len(r.content), 16):
            yield r.content[i : i + 16]

    async def embed(self, *, user_id, logical_model, inputs):
        return EmbeddingResponse(
            model="x", provider="x",
            vectors=[[1.0, 0.0, 0.0, 0.0] for _ in inputs],
            usage=TokenUsage(prompt_tokens=1, total_tokens=1),
        )


def _settings(tmp_path) -> Settings:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        openinterview_data_dir=str(tmp_path),
    )  # type: ignore[call-arg]


def _tiny_wav() -> bytes:
    samples = b"\x80\x80\x80\x80"
    data_chunk = b"data" + struct.pack("<I", len(samples)) + samples
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)
    body = b"WAVE" + fmt_chunk + data_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


async def _register_login(c: AsyncClient, email: str) -> str:
    await c.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "hunter2hunter2", "display_name": "U"},
    )
    r = await c.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "hunter2hunter2"},
    )
    return r.json()["access_token"]


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        ev = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:].strip()
            elif line.startswith("data: "):
                data += line[6:]
        if ev and data:
            try:
                out.append((ev, json.loads(data)))
            except Exception:
                out.append((ev, {"raw": data}))
    return out


@pytest.mark.asyncio
async def test_audio_interview_turn_and_evaluation(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    fake = FakeAudioGateway()
    app.state.gateway = fake
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "audio@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            from openinterview_db import Project, QAItem, QASet
            sm = app.state.db.sessionmaker
            user_id = uuid.UUID(
                (await c.get("/api/v1/me", headers=h)).json()["id"]
            )
            project_id = uuid.uuid4()
            qa_set_id = uuid.uuid4()
            async with sm() as s:
                s.add(Project(
                    id=project_id, user_id=user_id, name="demo",
                    source_type="zip", status="ready",
                    summary="x", architecture={"summary": "x"},
                ))
                s.add(QASet(
                    id=qa_set_id, user_id=user_id, project_id=project_id,
                    position="swe_generic", level="mid", status="ready", total=2,
                ))
                s.add(QAItem(
                    qa_set_id=qa_set_id, user_id=user_id,
                    category="architecture", level="mid",
                    question="Describe scaling.",
                    ideal_answer="Horizontal stateless tier...",
                    evidence=[],
                    difficulty=3, tags=["scaling"],
                ))
                s.add(QAItem(
                    qa_set_id=qa_set_id, user_id=user_id,
                    category="architecture", level="mid",
                    question="How do you handle caching?",
                    ideal_answer="LRU + write-through.",
                    evidence=[],
                    difficulty=3, tags=["cache"],
                ))
                await s.commit()

            r = await c.post("/api/v1/interviewer/sessions", headers=h, json={
                "project_id": str(project_id),
                "position": "swe_generic", "level": "mid", "n_questions": 2,
            })
            assert r.status_code == 200, r.text
            sid = r.json()["id"]

            # Bootstrap text turn so there's a current_question for eval.
            r = await c.post(
                f"/api/v1/interviewer/sessions/{sid}/messages",
                headers=h, json={"content": "I'm ready."},
            )
            assert r.status_code == 200

            # Audio turn.
            wav = _tiny_wav()
            r = await c.post(
                f"/api/v1/interviewer/sessions/{sid}/messages/audio",
                headers=h,
                files={"audio": ("clip.wav", wav, "audio/wav")},
                data={"language": "en"},
            )
            assert r.status_code == 200, r.text

            events = _parse_sse(r.text)
            kinds = [k for k, _ in events]
            assert "voice" in kinds
            assert "done" in kinds

            voice_ev = next(d for k, d in events if k == "voice")
            assert "FastAPI" in voice_ev["transcript"]
            assert voice_ev["voice"]["wpm"] == 125

            assert fake.analyze_calls
            call = fake.analyze_calls[0]
            assert call["mime"].startswith("audio/")
            assert call["lang"] == "en"

            # Per-turn evaluator must have seen the DELIVERY METRICS block on
            # at least one call (the audio turn). Earlier text-turn evals
            # won't have it.
            assert any("DELIVERY METRICS" in p for p in fake.eval_prompts), (
                fake.eval_prompts
            )
            audio_eval = next(
                p for p in fake.eval_prompts if "DELIVERY METRICS" in p
            )
            assert "delivery_score" in audio_eval
            assert "We use FastAPI" in audio_eval

            # Persisted user message should carry meta.voice.
            r = await c.get(
                f"/api/v1/interviewer/sessions/{sid}/messages", headers=h
            )
            msgs = r.json()
            user_audio_msg = next(
                m for m in msgs if m["role"] == "user" and "FastAPI" in m["content"]
            )
            assert user_audio_msg["meta"]["voice"]["wpm"] == 125
            assert user_audio_msg["meta"]["voice"]["filler_words"] == [
                {"word": "um", "count": 3}
            ]

            # End session -> aggregated delivery_score.
            r = await c.post(
                f"/api/v1/interviewer/sessions/{sid}:end", headers=h
            )
            assert r.status_code == 200, r.text
            ev = r.json()
            assert ev["delivery_score"] == pytest.approx(4.2)
            ds = ev["delivery_summary"]
            assert ds is not None
            assert ds["metrics"]["avg_wpm"] == pytest.approx(125)
            assert ds["metrics"]["filler_counts"][0]["word"] == "um"
            assert any(
                isinstance(n, dict)
                and (
                    "filler" in (n.get("note") or "").lower()
                    or "filler" in (n.get("area") or "").lower()
                )
                for n in ds["feedback"]
            )

            # Final-eval prompt also got DELIVERY METRICS.
            assert "DELIVERY METRICS" in fake.last_session_prompt
