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
        # If tools are present, the model "decides" not to call any -- emulate
        # an LLM that handles the question without browsing.
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


@pytest.mark.asyncio
async def test_interviewer_rejects_when_neither_target_provided(tmp_path) -> None:
    """The schema requires exactly one of resume_id / project_id; sending
    neither should fail validation rather than silently picking one."""
    app = create_app(_settings(tmp_path))
    app.state.gateway = FakeGateway()
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "neither@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            r = await c.post(
                "/api/v1/interviewer/sessions",
                headers=h,
                json={
                    "position": "swe_generic",
                    "level": "mid",
                    "n_questions": 2,
                },
            )
            assert r.status_code == 422


@pytest.mark.asyncio
async def test_resume_driven_interview_full_flow(tmp_path) -> None:
    """Resume-scoped mock interview: pre-seed a resume + a resume-scoped
    QA set with a claim-tagged item and confirm the agent surfaces the
    claim in its assistant message."""
    app = create_app(_settings(tmp_path))
    app.state.gateway = FakeGateway()
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "resi@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            from openinterview_db import QAItem, QASet, Resume
            sm = app.state.db.sessionmaker
            user_id = uuid.UUID(
                (await c.get("/api/v1/me", headers=h)).json()["id"]
            )
            resume_id = uuid.uuid4()
            qa_set_id = uuid.uuid4()
            claim_text = "Cut p99 latency 40% on the search service"
            async with sm() as s:
                s.add(
                    Resume(
                        id=resume_id,
                        user_id=user_id,
                        original_filename="ada.pdf",
                        content_type="application/pdf",
                        text="Ada — Staff SWE",
                        parsed={
                            "name": "Ada",
                            "skills": ["Postgres"],
                            "claims": [{"text": claim_text}],
                        },
                    )
                )
                s.add(
                    QASet(
                        id=qa_set_id,
                        user_id=user_id,
                        project_id=None,
                        resume_id=resume_id,
                        scope="resume",
                        position="swe_generic",
                        level="mid",
                        status="ready",
                        total=1,
                    )
                )
                s.add(
                    QAItem(
                        qa_set_id=qa_set_id,
                        user_id=user_id,
                        category="experience_claim",
                        level="mid",
                        question="Walk me through how you cut p99 latency.",
                        ideal_answer="Profile, find hot path, batch / cache.",
                        evidence=[],
                        difficulty=3,
                        tags=["latency"],
                        meta={
                            "claim": claim_text,
                            "claim_section": "experience",
                            "source_project_id": None,
                        },
                    )
                )
                await s.commit()

            r = await c.post(
                "/api/v1/interviewer/sessions",
                headers=h,
                json={
                    "resume_id": str(resume_id),
                    "position": "swe_generic",
                    "level": "mid",
                    "n_questions": 1,
                },
            )
            assert r.status_code == 200, r.text
            sess = r.json()
            sid = sess["id"]
            # Resume-scoped sessions don't pin a project.
            assert sess["project_id"] is None
            assert sess["target"]["scope"] == "resume"
            assert sess["target"]["resume_filename"] == "ada.pdf"

            # The first question is auto-asked at session creation; pull
            # messages and confirm the claim was surfaced in the assistant turn.
            r = await c.get(
                f"/api/v1/interviewer/sessions/{sid}/messages", headers=h
            )
            assert r.status_code == 200
            msgs = r.json()
            assert any(
                m["role"] == "assistant" and claim_text in m["content"]
                for m in msgs
            )

            # Title incorporates the resume filename so the user can tell
            # at-a-glance which resume drove this session.
            assert "ada" in (sess["title"] or "").lower()


@pytest.mark.asyncio
async def test_general_session_streaming(tmp_path) -> None:
    """The /general API mirrors the mentor flow but without project tools.

    Verifies create → list → SSE stream → message persistence → end."""
    app = create_app(_settings(tmp_path))
    app.state.gateway = FakeGateway()
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "g@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            r = await c.post(
                "/api/v1/general/sessions", headers=h, json={"title": "Hello"}
            )
            assert r.status_code == 200, r.text
            sess = r.json()
            sid = sess["id"]
            assert sess["mode"] == "general"
            assert sess["project_id"] is None

            # The session shows up in the list (and only in /general's list).
            r = await c.get("/api/v1/general/sessions", headers=h)
            assert r.status_code == 200
            assert any(s["id"] == sid for s in r.json())
            r = await c.get("/api/v1/mentor/sessions", headers=h)
            assert r.status_code == 200
            assert all(s["id"] != sid for s in r.json())

            # Stream a turn.
            r = await c.post(
                f"/api/v1/general/sessions/{sid}/messages",
                headers=h,
                json={"content": "Quick brainstorm please."},
            )
            assert r.status_code == 200
            events = _parse_sse(r.text)
            kinds = [e[0] for e in events]
            assert "token" in kinds
            assert "done" in kinds
            full = next(d.get("content", "") for k, d in events if k == "done")
            assert "thoughtful coaching response" in full

            # User + assistant messages are both persisted.
            r = await c.get(
                f"/api/v1/general/sessions/{sid}/messages", headers=h
            )
            assert r.status_code == 200
            roles = [m["role"] for m in r.json()]
            assert roles.count("user") == 1
            assert roles.count("assistant") == 1

            # End the session.
            r = await c.post(f"/api/v1/general/sessions/{sid}:end", headers=h)
            assert r.status_code == 200
            assert r.json()["status"] == "ended"


@pytest.mark.asyncio
async def test_general_session_auto_titles_then_rename(tmp_path) -> None:
    """A session created with title=None should be auto-titled by the
    first user message; the PATCH endpoint then lets users rename it."""
    app = create_app(_settings(tmp_path))
    app.state.gateway = FakeGateway()
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "rename@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            r = await c.post("/api/v1/general/sessions", headers=h, json={})
            sid = r.json()["id"]
            assert r.json()["title"] is None

            # Streaming a turn must trigger auto-titling on the user message.
            r = await c.post(
                f"/api/v1/general/sessions/{sid}/messages",
                headers=h,
                json={"content": "Quick brainstorm please, brand new product."},
            )
            assert r.status_code == 200
            r = await c.get("/api/v1/general/sessions", headers=h)
            sess = next(s for s in r.json() if s["id"] == sid)
            assert sess["title"] == "Quick brainstorm please, brand new product."

            # Rename to something custom.
            r = await c.patch(
                f"/api/v1/general/sessions/{sid}",
                headers=h,
                json={"title": "Brainstorm: Q3 launch"},
            )
            assert r.status_code == 200
            assert r.json()["title"] == "Brainstorm: Q3 launch"

            # Clear with null → goes back to untitled.
            r = await c.patch(
                f"/api/v1/general/sessions/{sid}",
                headers=h,
                json={"title": None},
            )
            assert r.status_code == 200
            assert r.json()["title"] is None


@pytest.mark.asyncio
async def test_general_session_rejects_mentor_id(tmp_path) -> None:
    """A mentor session id must not be mistaken for a /general session —
    /general endpoints filter by mode='general' and 404 otherwise."""
    app = create_app(_settings(tmp_path))
    app.state.gateway = FakeGateway()
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "g2@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            # Create a *mentor* session, then try to fetch it through /general.
            r = await c.post("/api/v1/mentor/sessions", headers=h, json={})
            mentor_sid = r.json()["id"]

            r = await c.get(
                f"/api/v1/general/sessions/{mentor_sid}/messages", headers=h
            )
            assert r.status_code == 404
            r = await c.post(
                f"/api/v1/general/sessions/{mentor_sid}/messages",
                headers=h,
                json={"content": "hi"},
            )
            assert r.status_code == 404
