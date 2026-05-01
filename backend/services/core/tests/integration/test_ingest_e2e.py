"""End-to-end ingestion test using an in-process fake gateway.

Builds a tiny zip in memory, uploads, runs ingestion synchronously via the
test-only `_run_now` endpoint, then asserts on persisted summaries, files,
diagrams, vector store contents, and resume claim mappings.
"""
from __future__ import annotations

import io
import json
import os
import zipfile

import pytest

pytest.importorskip("aiosqlite")

from httpx import ASGITransport, AsyncClient

from openinterview_core.app import create_app
from openinterview_core.config import Settings
from openinterview_core.infra.vector import vector_collection_for_user_project
from openinterview_schemas import (
    ChatCompletionResponse,
    EmbeddingResponse,
    TokenUsage,
)


# ---------- Fake Gateway ----------

class FakeGateway:
    def __init__(self) -> None:
        self.chat_calls = 0
        self.embed_calls = 0

    async def chat(self, *, user_id, logical_model, messages, temperature=None, max_tokens=None):
        self.chat_calls += 1
        prompt = messages[-1].content
        # Return deterministic JSON for prompts that demand it.
        if "STRICT JSON" in prompt and "components" in prompt:
            content = json.dumps({
                "summary": "Test project: a tiny FastAPI service with a calculator module.",
                "components": [
                    {"name": "api", "role": "http surface", "deps": ["calc"]},
                    {"name": "calc", "role": "math logic", "deps": []},
                ],
            })
        elif "STRICT JSON" in prompt and "interesting" in prompt.lower() or "title" in prompt.lower() and "interviewer" in prompt.lower():
            content = json.dumps([
                {"title": "Chose FastAPI over Flask", "detail": "for async support", "refs": ["api"]},
                {"title": "Pure-function calculator", "detail": "easier to test", "refs": ["calc"]},
            ])
        elif "STRICT JSON" in prompt and "claims" in prompt.lower():
            content = json.dumps({
                "name": "Jane Doe",
                "contacts": {"email": "jane@example.com"},
                "skills": ["python", "fastapi"],
                "experience": [],
                "projects": [],
                "education": [],
                "claims": [{"text": "Built a calculator service in FastAPI", "section": "projects"}],
            })
        elif "Mermaid" in prompt:
            content = "flowchart LR\n  api --> calc"
        elif "confidence" in prompt.lower() and "claim" in prompt.lower():
            content = json.dumps({"confidence": 80})
        else:
            # File / module summary fallback
            content = "Short deterministic summary."

        return ChatCompletionResponse(
            id="x",
            model="fake",
            provider="fake",
            content=content,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            finish_reason="stop",
        )

    async def embed(self, *, user_id, logical_model, inputs):
        self.embed_calls += 1
        # Deterministic embeddings: hash-based 8-dim vectors.
        vectors: list[list[float]] = []
        for s in inputs:
            h = hash(s)
            vectors.append([(h >> i) & 1 for i in range(8)])
        return EmbeddingResponse(
            model="fake-embed",
            provider="fake",
            vectors=vectors,
            usage=TokenUsage(prompt_tokens=len(inputs), total_tokens=len(inputs)),
        )


# ---------- Helpers ----------

PYTHON_SAMPLE = '''\
"""Tiny calculator module."""

def add(a, b):
    """Return a + b."""
    return a + b


def mul(a, b):
    return a * b


class Calculator:
    def add(self, a, b):
        return add(a, b)
'''

API_SAMPLE = '''\
from fastapi import FastAPI
from .calc import add

app = FastAPI()


@app.get("/add")
def add_endpoint(a: int, b: int) -> int:
    return add(a, b)
'''

README_SAMPLE = """# Demo

A FastAPI calculator service.

## Endpoints
- /add: returns a + b
"""


def _make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("demo/api.py", API_SAMPLE)
        zf.writestr("demo/calc.py", PYTHON_SAMPLE)
        zf.writestr("demo/README.md", README_SAMPLE)
    return buf.getvalue()


def _settings(tmp_path) -> Settings:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        openinterview_data_dir=str(tmp_path),
    )  # type: ignore[call-arg]


async def _register_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "hunter2hunter2", "display_name": "U"},
    )
    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2hunter2"}
    )
    return r.json()["access_token"]


# ---------- Tests ----------

@pytest.mark.asyncio
async def test_project_ingest_e2e(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    fake = FakeGateway()
    app.state.gateway = fake  # override AFTER creation

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "u@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            # Upload (kicks off background ingest, but we'll re-run synchronously).
            zip_bytes = _make_zip()
            r = await c.post(
                "/api/v1/projects",
                headers=h,
                data={"name": "demo"},
                files={"file": ("demo.zip", zip_bytes, "application/zip")},
            )
            assert r.status_code == 201, r.text
            project_id = r.json()["id"]

            # Run synchronously.
            r = await c.post(f"/api/v1/projects/{project_id}/_run_now", headers=h)
            assert r.status_code == 200, r.text

            # Project detail
            r = await c.get(f"/api/v1/projects/{project_id}", headers=h)
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ready"
            assert "calculator" in (body["summary"] or "").lower() or body["summary"]
            assert body["architecture"] is not None
            assert body["interesting_decisions"] is not None

            # Files
            r = await c.get(f"/api/v1/projects/{project_id}/files", headers=h)
            files = r.json()
            assert {f["rel_path"] for f in files} == {
                "demo/api.py",
                "demo/calc.py",
                "demo/README.md",
            }
            for f in files:
                assert f["summary"]

            # Diagrams
            r = await c.get(f"/api/v1/projects/{project_id}/diagrams", headers=h)
            diagrams = r.json()
            assert len(diagrams) >= 1
            assert "flowchart" in diagrams[0]["mermaid"].lower()

            # Vector store has chunks
            user_id = (await c.get("/api/v1/me", headers=h)).json()["id"]
            collection = vector_collection_for_user_project(user_id, project_id)
            store = app.state.vector_store
            # use a deterministic embedding to query (any vector returns top-k)
            results = await store.query(collection=collection, embedding=[1] * 8, k=5)
            assert results, "vector store should have ingested chunks"
            assert any(m.metadata.get("kind") == "code" for m in results)

            # Gateway calls were made
            assert fake.embed_calls >= 1
            assert fake.chat_calls >= 4  # files + module + project + diagram + interesting


@pytest.mark.asyncio
async def test_resume_ingest_with_claim_mapping(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    fake = FakeGateway()
    app.state.gateway = fake

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "u2@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            # Upload a project first
            r = await c.post(
                "/api/v1/projects",
                headers=h,
                data={"name": "demo"},
                files={"file": ("demo.zip", _make_zip(), "application/zip")},
            )
            project_id = r.json()["id"]
            await c.post(f"/api/v1/projects/{project_id}/_run_now", headers=h)

            # Upload resume (txt)
            resume_text = (
                "Jane Doe\nEmail: jane@example.com\nProjects:\n"
                "- Built a calculator service in FastAPI\n"
            )
            r = await c.post(
                "/api/v1/resumes",
                headers=h,
                data={"project_ids": project_id},
                files={"file": ("resume.txt", resume_text.encode("utf-8"), "text/plain")},
            )
            assert r.status_code == 201, r.text
            resume_id = r.json()["id"]

            r = await c.post(
                f"/api/v1/resumes/{resume_id}/_run_now",
                headers=h,
                params={"project_ids": project_id},
            )
            assert r.status_code == 200

            r = await c.get(f"/api/v1/resumes/{resume_id}", headers=h)
            body = r.json()
            assert body["parsed"] is not None
            assert any(c["text"].startswith("Built a calculator")
                       for c in body["parsed"]["claims"])

            r = await c.get(f"/api/v1/resumes/{resume_id}/claim-mappings", headers=h)
            mappings = r.json()
            assert len(mappings) >= 1
            assert mappings[0]["project_id"] == project_id
            assert mappings[0]["confidence"] == 80
