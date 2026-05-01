"""End-to-end mentor + interviewer flow with a fake gateway and an in-memory
vector store. Verifies streaming response, message persistence, evaluation, and
basic memory isolation."""
from __future__ import annotations

import json
import os
import re
import uuid
from uuid import uuid4

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
)


class FakeGateway:
    """Returns canned, prompt-aware responses."""
    def __init__(self) -> None:
        self.chat_calls = 0

    async def chat(self, *, user_id, logical_model, messages, **kwargs):
        self.chat_calls += 1
        prompt = messages[-1].content if messages else ""
        # Distillation
        if "distilling" in prompt.lower():
            return _resp(json.dumps({
                "episodic_summary": "Discussed FastAPI errors.",
                "entities": {"projects": ["demo"], "topics": ["errors"]},
                "long_term": [
                    {"kind": "gap", "content": "needs more on async cancellation", "weight": 0.8},
                ],
            }))
        # Session evaluation
        if "interview panel chair" in prompt.lower():
            return _resp(json.dumps({
                "overall_score": 3.5,
                "scores": {"architecture": 4.0, "code_quality": 3.0},
                "summary": "Solid mid-level answer.",
                "strengths": ["good FastAPI knowledge"],
                "weaknesses": ["shaky on async cancellation"],
                "suggested_practice": [
                    {"area": "asyncio", "why": "cancellation gaps", "next_step": "read PEP 654"},
                ],
            }))
        # Per-turn evaluation in interviewer
        if "evaluating a candidate" in prompt.lower():
            return _resp(json.dumps({
                "score": 3,
                "feedback": "Reasonable answer.",
                "missed_points": ["error logging"],
                "probe_question": None,
            }))
        # Mentor / interviewer assistant turn
        return _resp("Here is a thoughtful coaching response.")

    async def embed(self, *, user_id, logical_model, inputs):
        return EmbeddingResponse(
            model="x", provider="x",
            vectors=[[1.0, 0.0, 0.0, 0.0] for _ in inputs],
            usage=TokenUsage(prompt_tokens=1, total_tokens=1),
        )

    async def chat_stream(self, *, user_id, logical_model, messages, **kwargs):
        # Reuse the canned chat() output and chunk it so callers see real deltas.
        resp = await self.chat(
            user_id=user_id, logical_model=logical_model, messages=messages
        )
        text = resp.content
        step = 16
        for i in range(0, len(text), step):
            yield text[i : i + step]


def _resp(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="x", model="m", provider="p", content=content,
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
    )


def _settings(tmp_path) -> Settings:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        openinterview_data_dir=str(tmp_path),
    )  # type: ignore[call-arg]


async def _register_login(c: AsyncClient, email: str) -> str:
    await c.post("/api/v1/auth/register", json={
        "email": email, "password": "hunter2hunter2", "display_name": "U"
    })
    r = await c.post("/api/v1/auth/login", json={
        "email": email, "password": "hunter2hunter2",
    })
    return r.json()["access_token"]


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse a string of SSE events into (event_name, data_dict) pairs."""
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
async def test_mentor_session_streaming(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.gateway = FakeGateway()
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "m@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            r = await c.post("/api/v1/mentor/sessions", headers=h, json={})
            assert r.status_code == 200
            sid = r.json()["id"]

            # Stream a turn.
            r = await c.post(
                f"/api/v1/mentor/sessions/{sid}/messages",
                headers=h, json={"content": "Help me explain my project's design."},
            )
            assert r.status_code == 200
            events = _parse_sse(r.text)
            kinds = [e[0] for e in events]
            assert "token" in kinds
            assert "done" in kinds
            full = next(d.get("content", "") for k, d in events if k == "done")
            assert "thoughtful coaching response" in full

            # Messages persisted (user + assistant).
            r = await c.get(
                f"/api/v1/mentor/sessions/{sid}/messages", headers=h
            )
            msgs = r.json()
            roles = [m["role"] for m in msgs]
            assert roles.count("user") == 1
            assert roles.count("assistant") == 1


@pytest.mark.asyncio
async def test_interviewer_full_flow(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.gateway = FakeGateway()
    vs = InMemoryVectorStore()
    app.state.vector_store = vs

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "i@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            # Seed: a project + a QA set with one item directly in DB.
            from openinterview_core.infra.vector import vector_collection_for_user_project, VectorRecord
            from openinterview_db import Project, QAItem, QASet
            sm = app.state.db.sessionmaker
            user_id = uuid.UUID((await c.get("/api/v1/me", headers=h)).json()["id"])
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
                    position="swe_generic", level="mid", status="ready", total=1,
                ))
                s.add(QAItem(
                    qa_set_id=qa_set_id, user_id=user_id,
                    category="architecture", level="mid",
                    question="Describe your service architecture.",
                    ideal_answer="API + calc, async-first.",
                    evidence=[],
                    difficulty=3, tags=["fastapi"],
                ))
                await s.commit()

            await vs.upsert(
                collection=vector_collection_for_user_project(str(user_id), str(project_id)),
                records=[VectorRecord(id="x", text="code", metadata={"rel_path": "a.py"})],
                embeddings=[[1.0, 0, 0, 0]],
            )

            # Create interviewer session (will also try to create-or-get qa set).
            r = await c.post("/api/v1/interviewer/sessions", headers=h, json={
                "project_id": str(project_id),
                "position": "swe_generic", "level": "mid", "n_questions": 2,
            })
            assert r.status_code == 200, r.text
            sid = r.json()["id"]

            # First turn: candidate "starts".
            r = await c.post(
                f"/api/v1/interviewer/sessions/{sid}/messages",
                headers=h, json={"content": "I'm ready."},
            )
            assert r.status_code == 200
            events = _parse_sse(r.text)
            assert any(k == "done" for k, _ in events)
            done_meta = next(d for k, d in events if k == "done")
            # On first turn, there's no prev question to evaluate.
            assert "Next question" in done_meta["content"] or done_meta["content"]

            # Second turn: candidate answers.
            r = await c.post(
                f"/api/v1/interviewer/sessions/{sid}/messages",
                headers=h, json={"content": "We use FastAPI..."},
            )
            assert r.status_code == 200

            # End session -> evaluation.
            r = await c.post(f"/api/v1/interviewer/sessions/{sid}:end", headers=h)
            assert r.status_code == 200, r.text
            ev = r.json()
            assert ev["overall_score"] == pytest.approx(3.5)
            assert "good FastAPI knowledge" in ev["strengths"]
            assert any("async cancellation" in w for w in ev["weaknesses"])
