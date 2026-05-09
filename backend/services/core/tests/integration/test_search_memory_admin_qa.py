from __future__ import annotations

from uuid import UUID, uuid4

import pytest

pytest.importorskip("aiosqlite")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from openinterview_core.app import create_app  # noqa: E402
from openinterview_core.config import Settings  # noqa: E402
from openinterview_core.infra.db.chat_repository import SqlChatRepository  # noqa: E402
from openinterview_core.infra.db.memory_repository import SqlMemoryRepository  # noqa: E402
from openinterview_db import QASet  # noqa: E402


def _settings(tmp_path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        openinterview_env="local",
    )


async def _register_login(client: AsyncClient, email: str) -> tuple[dict, str]:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "hunter2hunter2",
            "display_name": email.split("@")[0],
        },
    )
    assert r.status_code == 201, r.text
    user = r.json()
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text
    return user, r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_chat_history_server_search_and_memory_pin_api(tmp_path):
    app = create_app(_settings(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            user, token = await _register_login(client, "search@example.com")
            user_id = UUID(user["id"])
            async with app.state.db.sessionmaker() as session:
                chat = SqlChatRepository(session)
                sess = await chat.create_session(
                    user_id=user_id,
                    mode="general",
                    title="Storage design",
                )
                await chat.append_message(
                    session_id=sess.id,
                    user_id=user_id,
                    role="user",
                    content="Compare LSM storage compaction tradeoffs.",
                )
                memory = await SqlMemoryRepository(session).add_long_term(
                    user_id=user_id,
                    kind="fact",
                    content="Prefers database internals examples.",
                    weight=0.8,
                )

            r = await client.get(
                "/api/v1/chat-history/search?q=compaction&mode=general",
                headers=_auth(token),
            )
            assert r.status_code == 200, r.text
            rows = r.json()
            assert rows[0]["session"]["id"] == str(sess.id)
            assert "compaction" in rows[0]["snippet"].lower()

            r = await client.patch(
                f"/api/v1/memory/long-term/{memory.id}",
                json={"pinned": True},
                headers=_auth(token),
            )
            assert r.status_code == 200, r.text
            assert r.json()["pinned"] is True

            r = await client.get(
                "/api/v1/memory/long-term?pinned=true",
                headers=_auth(token),
            )
            assert r.status_code == 200, r.text
            assert [row["id"] for row in r.json()] == [str(memory.id)]


@pytest.mark.asyncio
async def test_admin_qa_review_endpoints(tmp_path):
    app = create_app(_settings(tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            admin, token = await _register_login(client, "admin-qa@example.com")
            qa_set_id = uuid4()
            async with app.state.db.sessionmaker() as session:
                session.add(
                    QASet(
                        id=qa_set_id,
                        user_id=UUID(admin["id"]),
                        project_id=None,
                        resume_id=None,
                        scope="project",
                        position="swe_generic",
                        level="mid",
                        status="ready",
                        total=0,
                    )
                )
                await session.commit()

            r = await client.get("/api/v1/admin/qa-sets", headers=_auth(token))
            assert r.status_code == 200, r.text
            assert any(row["id"] == str(qa_set_id) for row in r.json())

            r = await client.patch(
                f"/api/v1/admin/qa-sets/{qa_set_id}/review",
                json={"review_status": "approved", "review_notes": "Looks good"},
                headers=_auth(token),
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["review_status"] == "approved"
            assert body["review_notes"] == "Looks good"
