from __future__ import annotations

import os

import pytest

pytest.importorskip("aiosqlite")

from httpx import ASGITransport, AsyncClient

from openinterview_core.app import create_app
from openinterview_core.config import Settings


def _settings() -> Settings:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    return Settings()  # type: ignore[call-arg]


async def _register_login(client: AsyncClient, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "hunter2hunter2", "display_name": "U"},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "hunter2hunter2"},
    )
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_api_key_crud_and_isolation() -> None:
    app = create_app(_settings())
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            tok_a = await _register_login(c, "a3@b.com")
            tok_b = await _register_login(c, "b3@b.com")

            # A creates a key
            r = await c.post(
                "/api/v1/me/api-keys",
                headers={"Authorization": f"Bearer {tok_a}"},
                json={"provider": "openai", "label": "personal", "plaintext": "sk-aaa"},
            )
            assert r.status_code == 201, r.text
            key_id = r.json()["id"]
            assert "plaintext" not in r.json()

            # A lists -> 1
            r = await c.get(
                "/api/v1/me/api-keys", headers={"Authorization": f"Bearer {tok_a}"}
            )
            assert len(r.json()) == 1

            # B lists -> 0 (isolation)
            r = await c.get(
                "/api/v1/me/api-keys", headers={"Authorization": f"Bearer {tok_b}"}
            )
            assert r.json() == []

            # B cannot delete A's key
            r = await c.delete(
                f"/api/v1/me/api-keys/{key_id}",
                headers={"Authorization": f"Bearer {tok_b}"},
            )
            assert r.status_code == 404

            # A deletes
            r = await c.delete(
                f"/api/v1/me/api-keys/{key_id}",
                headers={"Authorization": f"Bearer {tok_a}"},
            )
            assert r.status_code == 204
