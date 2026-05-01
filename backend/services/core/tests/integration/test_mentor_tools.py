"""Mentor agent tool-loop integration: a fake gateway that asks for read_file
once, then produces a streaming final answer."""
from __future__ import annotations

import io
import json
import os
import uuid
import zipfile

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
    ToolCall,
)
from openinterview_storage import paths as sp


class ToolyFakeGateway:
    """First chat() with tools returns a tool_call to read_file('src/app.py').
    Second chat() with tools returns no tool_calls (signaling done).
    chat_stream() yields the final answer in chunks."""

    def __init__(self) -> None:
        self.chat_calls = 0
        self.tool_calls_seen = 0

    async def chat(self, *, user_id, logical_model, messages, tools=None, tool_choice=None, **kwargs):
        self.chat_calls += 1
        if tools and self.tool_calls_seen == 0:
            self.tool_calls_seen += 1
            return ChatCompletionResponse(
                id="x",
                model="m",
                provider="p",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        type="function",
                        function={
                            "name": "read_file",
                            "arguments": json.dumps({"path": "src/app.py"}),
                        },
                    )
                ],
                usage=TokenUsage(),
                finish_reason="tool_calls",
            )
        # No more tool calls -> the agent will switch to streaming pass.
        return ChatCompletionResponse(
            id="x", model="m", provider="p",
            content="", usage=TokenUsage(), finish_reason="stop",
        )

    async def embed(self, *, user_id, logical_model, inputs):
        return EmbeddingResponse(
            model="x", provider="x",
            vectors=[[1.0, 0.0, 0.0, 0.0] for _ in inputs],
            usage=TokenUsage(),
        )

    async def chat_stream(self, *, user_id, logical_model, messages, **kwargs):
        # Should be called only after the tool loop has assembled enough context.
        # Verify a `tool` role message exists in the conversation.
        roles = [m.role for m in messages]
        assert "tool" in roles, f"expected tool message in conversation, got {roles}"
        text = "Based on the file you opened, your auth flow uses JWT tokens."
        for i in range(0, len(text), 16):
            yield text[i : i + 16]


def _settings(tmp_path) -> Settings:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        openinterview_data_dir=str(tmp_path),
    )  # type: ignore[call-arg]


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


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


async def _register_login(c: AsyncClient, email: str) -> str:
    await c.post("/api/v1/auth/register", json={
        "email": email, "password": "hunter2hunter2", "display_name": "U"
    })
    r = await c.post("/api/v1/auth/login", json={
        "email": email, "password": "hunter2hunter2",
    })
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_mentor_uses_tools_when_project_attached(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    fake = ToolyFakeGateway()
    app.state.gateway = fake
    app.state.vector_store = InMemoryVectorStore()

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok = await _register_login(c, "tools@x.com")
            h = {"Authorization": f"Bearer {tok}"}

            user_id = uuid.UUID(
                (await c.get("/api/v1/me", headers=h)).json()["id"]
            )
            project_id = uuid.uuid4()

            # Seed a "ready" project with a source.zip blob the agent can browse.
            from openinterview_db import Project
            sm = app.state.db.sessionmaker
            async with sm() as s:
                s.add(Project(
                    id=project_id, user_id=user_id, name="demo",
                    source_type="zip", status="ready",
                    summary="x", architecture={"summary": "x"},
                ))
                await s.commit()

            zip_data = _zip_bytes({
                "src/app.py": b"# JWT auth pseudo-code\nTOKEN = 'jwt'\n",
                "README.md": b"# demo",
            })
            await app.state.blob.put_bytes(
                f"{sp.user_root(user_id)}/projects/{project_id}/source.zip",
                zip_data,
            )

            # Create mentor session bound to this project.
            r = await c.post(
                "/api/v1/mentor/sessions",
                headers=h, json={"project_id": str(project_id), "title": "tools test"},
            )
            assert r.status_code == 200
            sid = r.json()["id"]

            r = await c.post(
                f"/api/v1/mentor/sessions/{sid}/messages",
                headers=h, json={"content": "Where is JWT handled?"},
            )
            assert r.status_code == 200, r.text
            events = _parse_sse(r.text)
            kinds = [e[0] for e in events]

            assert "tool_call" in kinds, kinds
            assert "tool_result" in kinds
            assert "token" in kinds
            assert "done" in kinds

            tc_data = next(d for k, d in events if k == "tool_call")
            assert tc_data["name"] == "read_file"
            assert tc_data["args"]["path"] == "src/app.py"

            tr_data = next(d for k, d in events if k == "tool_result")
            assert "src/app.py" in tr_data["preview"] or "JWT" in tr_data["preview"]

            done = next(d for k, d in events if k == "done")
            assert "auth flow" in done["content"]

            # Two chat() turns expected: one tool call, one "done" decision.
            assert fake.chat_calls == 2

            # Tool trace persists on the assistant message's meta.
            r = await c.get(
                f"/api/v1/mentor/sessions/{sid}/messages", headers=h
            )
            assert r.status_code == 200
            msgs = r.json()
            assistant = [m for m in msgs if m["role"] == "assistant"][-1]
            assert assistant["meta"] is not None
            tools = assistant["meta"].get("tools")
            assert tools and len(tools) == 1
            assert tools[0]["name"] == "read_file"
            assert tools[0]["args"]["path"] == "src/app.py"
            assert tools[0]["done"] is True
            assert tools[0]["preview"]
