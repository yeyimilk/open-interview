from __future__ import annotations

import pytest

pytest.importorskip("aiosqlite")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from openinterview_core.app import create_app  # noqa: E402
from openinterview_core.config import Settings  # noqa: E402


def _settings(
    *,
    database_url: str = "sqlite+aiosqlite:///:memory:",
    bootstrap_admin_email: str | None = None,
) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url=database_url,
        openinterview_bootstrap_admin_email=bootstrap_admin_email,
    )


async def _register(client: AsyncClient, email: str, name: str) -> dict:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "hunter2hunter2",
            "display_name": name,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _login(client: AsyncClient, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_first_registered_user_bootstraps_as_admin() -> None:
    app = create_app(_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            first = await _register(client, "owner@example.com", "Owner")
            second = await _register(client, "member@example.com", "Member")

            assert first["is_admin"] is True
            assert second["is_admin"] is False


@pytest.mark.asyncio
async def test_bootstrap_admin_email_promotes_existing_user(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'bootstrap.db'}"

    app = create_app(_settings(database_url=db_url))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            await _register(client, "owner-bootstrap@example.com", "Owner")
            member = await _register(client, "member-bootstrap@example.com", "Member")
            assert member["is_admin"] is False

    app = create_app(
        _settings(
            database_url=db_url,
            bootstrap_admin_email="member-bootstrap@example.com",
        )
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            token = await _login(client, "member-bootstrap@example.com")
            r = await client.get("/api/v1/admin/users", headers=_auth(token))
            assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_users_blocks_non_admins() -> None:
    app = create_app(_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            await _register(client, "owner2@example.com", "Owner")
            await _register(client, "member2@example.com", "Member")
            member_token = await _login(client, "member2@example.com")

            r = await client.get("/api/v1/admin/users", headers=_auth(member_token))
            assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_admin_can_list_update_and_promote_users() -> None:
    app = create_app(_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            await _register(client, "owner3@example.com", "Owner")
            member = await _register(client, "member3@example.com", "Member")
            owner_token = await _login(client, "owner3@example.com")
            member_token = await _login(client, "member3@example.com")

            r = await client.get("/api/v1/admin/users", headers=_auth(owner_token))
            assert r.status_code == 200, r.text
            assert {u["email"] for u in r.json()} == {
                "owner3@example.com",
                "member3@example.com",
            }

            r = await client.patch(
                f"/api/v1/admin/users/{member['id']}",
                headers=_auth(owner_token),
                json={"is_admin": True, "tier": "pro"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["is_admin"] is True
            assert r.json()["tier"] == "pro"

            r = await client.get("/api/v1/admin/users", headers=_auth(member_token))
            assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_admin_cannot_remove_last_admin() -> None:
    app = create_app(_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            owner = await _register(client, "owner4@example.com", "Owner")
            owner_token = await _login(client, "owner4@example.com")

            r = await client.patch(
                f"/api/v1/admin/users/{owner['id']}",
                headers=_auth(owner_token),
                json={"is_admin": False},
            )
            assert r.status_code == 400, r.text
            assert r.json()["detail"] == "cannot remove the last admin"
