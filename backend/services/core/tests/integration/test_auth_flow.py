"""End-to-end auth flow against an in-memory SQLite-backed app.

Uses aiosqlite to avoid requiring Postgres for unit/integration runs.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("aiosqlite")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from openinterview_core.app import create_app  # noqa: E402
from openinterview_core.config import Settings  # noqa: E402


def _settings() -> Settings:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    s = Settings()  # type: ignore[call-arg]
    return s


@pytest.mark.asyncio
async def test_register_login_me() -> None:
    app = create_app(_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # trigger lifespan
        async with app.router.lifespan_context(app):
            r = await client.post(
                "/api/v1/auth/register",
                json={"email": "a@b.com", "password": "hunter2hunter2", "display_name": "A"},
            )
            assert r.status_code == 201, r.text

            r = await client.post(
                "/api/v1/auth/login",
                json={"email": "a@b.com", "password": "hunter2hunter2"},
            )
            assert r.status_code == 200, r.text
            tok = r.json()["access_token"]

            r = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {tok}"})
            assert r.status_code == 200, r.text
            assert r.json()["email"] == "a@b.com"


@pytest.mark.asyncio
async def test_isolation_user_b_cannot_use_user_a_token_arbitrarily() -> None:
    """Sanity: a token for user A only resolves to user A's profile."""
    app = create_app(_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            await client.post(
                "/api/v1/auth/register",
                json={"email": "a2@b.com", "password": "hunter2hunter2", "display_name": "A"},
            )
            await client.post(
                "/api/v1/auth/register",
                json={"email": "b2@b.com", "password": "hunter2hunter2", "display_name": "B"},
            )
            la = await client.post(
                "/api/v1/auth/login",
                json={"email": "a2@b.com", "password": "hunter2hunter2"},
            )
            ta = la.json()["access_token"]
            r = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {ta}"})
            assert r.json()["email"] == "a2@b.com"
