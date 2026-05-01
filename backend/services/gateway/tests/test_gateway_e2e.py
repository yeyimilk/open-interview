from __future__ import annotations

import hashlib
import os
import uuid

import pytest

pytest.importorskip("aiosqlite")

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from openinterview_db import Base, User, UserApiKey, make_engine, make_sessionmaker

from openinterview_gateway.app import create_app
from openinterview_gateway.config import Settings
from openinterview_gateway.domain.gateway_service import GatewayService
from openinterview_gateway.wiring import build_service

from .fakes import FakeProvider


SERVICE_TOKEN = "svc-token-for-tests"
MASTER_KEY = "master-key-for-tests-please-change!"


def _encrypt(plaintext: str) -> bytes:
    derived = hashlib.sha256(MASTER_KEY.encode("utf-8")).digest()
    nonce = b"\x00" * 12
    return nonce + AESGCM(derived).encrypt(nonce, plaintext.encode("utf-8"), None)


def _settings(yaml_dir, *, shared_openai: str | None = None) -> Settings:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    return Settings(
        gateway_service_token=SERVICE_TOKEN,
        openinterview_master_key=MASTER_KEY,
        models_yaml_path=str(yaml_dir / "models.yaml"),
        tiers_yaml_path=str(yaml_dir / "tiers.yaml"),
        database_url="sqlite+aiosqlite:///:memory:",
        shared_key_openai=shared_openai,
    )  # type: ignore[call-arg]


async def _seed_user(sm: async_sessionmaker, *, with_byo: bool, tier: str = "free") -> uuid.UUID:
    async with sm() as s:
        u = User(
            email=f"{uuid.uuid4()}@x.com",
            password_hash="x",
            display_name="t",
            tier=tier,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        if with_byo:
            s.add(
                UserApiKey(
                    user_id=u.id,
                    provider="openai",
                    label="byo",
                    encrypted_key=_encrypt("sk-byo-user-key"),
                )
            )
            await s.commit()
        return u.id


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {SERVICE_TOKEN}"}


@pytest.mark.asyncio
async def test_chat_byo_path_uses_user_key_and_logs(yaml_tmp) -> None:
    s = _settings(yaml_tmp)
    app = create_app(s)
    fake = FakeProvider()
    app.state.provider_override = fake

    async with app.router.lifespan_context(app):
        sm = app.state.sessionmaker
        user_id = await _seed_user(sm, with_byo=True)

        async with _client(app) as c:
            r = await c.post(
                "/v1/chat/completions",
                headers=_auth_headers(),
                json={
                    "user_id": str(user_id),
                    "logical_model": "chat-test",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["content"] == "echo:hi"
        assert body["usage"]["total_tokens"] == 15

        assert len(fake.chat_calls) == 1
        assert fake.chat_calls[0]["api_key"] == "sk-byo-user-key"

        # usage log row
        from openinterview_db import GatewayUsageLog
        from sqlalchemy import select

        async with sm() as session:
            rows = list((await session.execute(select(GatewayUsageLog))).scalars())
        assert len(rows) == 1
        assert rows[0].mode == "byo"
        assert rows[0].provider == "openai"
        assert rows[0].total_tokens == 15
        assert rows[0].status == 200


@pytest.mark.asyncio
async def test_chat_shared_path_when_no_byo(yaml_tmp) -> None:
    s = _settings(yaml_tmp, shared_openai="sk-admin-shared")
    app = create_app(s)
    fake = FakeProvider()
    app.state.provider_override = fake

    async with app.router.lifespan_context(app):
        sm = app.state.sessionmaker
        user_id = await _seed_user(sm, with_byo=False, tier="free")

        async with _client(app) as c:
            r = await c.post(
                "/v1/chat/completions",
                headers=_auth_headers(),
                json={
                    "user_id": str(user_id),
                    "logical_model": "chat-test",
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )
        assert r.status_code == 200, r.text
        assert fake.chat_calls[0]["api_key"] == "sk-admin-shared"


@pytest.mark.asyncio
async def test_rate_limit_only_for_shared(yaml_tmp) -> None:
    """free tier = 3 rpm. Shared path: 4th call -> 429. BYO path: never limited."""
    s = _settings(yaml_tmp, shared_openai="sk-admin-shared")
    app = create_app(s)
    app.state.provider_override = FakeProvider()

    async with app.router.lifespan_context(app):
        sm = app.state.sessionmaker
        u_shared = await _seed_user(sm, with_byo=False, tier="free")
        u_byo = await _seed_user(sm, with_byo=True, tier="free")

        async with _client(app) as c:
            # 3 OK
            for _ in range(3):
                r = await c.post(
                    "/v1/chat/completions",
                    headers=_auth_headers(),
                    json={
                        "user_id": str(u_shared),
                        "logical_model": "chat-test",
                        "messages": [{"role": "user", "content": "x"}],
                    },
                )
                assert r.status_code == 200
            # 4th -> 429
            r = await c.post(
                "/v1/chat/completions",
                headers=_auth_headers(),
                json={
                    "user_id": str(u_shared),
                    "logical_model": "chat-test",
                    "messages": [{"role": "user", "content": "x"}],
                },
            )
            assert r.status_code == 429

            # BYO is unlimited
            for _ in range(10):
                r = await c.post(
                    "/v1/chat/completions",
                    headers=_auth_headers(),
                    json={
                        "user_id": str(u_byo),
                        "logical_model": "chat-test",
                        "messages": [{"role": "user", "content": "x"}],
                    },
                )
                assert r.status_code == 200


@pytest.mark.asyncio
async def test_missing_service_token_rejected(yaml_tmp) -> None:
    s = _settings(yaml_tmp, shared_openai="sk-x")
    app = create_app(s)
    app.state.provider_override = FakeProvider()

    async with app.router.lifespan_context(app):
        sm = app.state.sessionmaker
        user_id = await _seed_user(sm, with_byo=False)

        async with _client(app) as c:
            r = await c.post(
                "/v1/chat/completions",
                json={
                    "user_id": str(user_id),
                    "logical_model": "chat-test",
                    "messages": [{"role": "user", "content": "x"}],
                },
            )
            assert r.status_code == 401


@pytest.mark.asyncio
async def test_no_credentials_returns_503(yaml_tmp) -> None:
    s = _settings(yaml_tmp, shared_openai=None)
    app = create_app(s)
    app.state.provider_override = FakeProvider()

    async with app.router.lifespan_context(app):
        sm = app.state.sessionmaker
        user_id = await _seed_user(sm, with_byo=False)

        async with _client(app) as c:
            r = await c.post(
                "/v1/chat/completions",
                headers=_auth_headers(),
                json={
                    "user_id": str(user_id),
                    "logical_model": "chat-test",
                    "messages": [{"role": "user", "content": "x"}],
                },
            )
            assert r.status_code == 503


@pytest.mark.asyncio
async def test_embeddings_path(yaml_tmp) -> None:
    s = _settings(yaml_tmp)
    app = create_app(s)
    app.state.provider_override = FakeProvider()

    async with app.router.lifespan_context(app):
        sm = app.state.sessionmaker
        user_id = await _seed_user(sm, with_byo=True)

        async with _client(app) as c:
            r = await c.post(
                "/v1/embeddings",
                headers=_auth_headers(),
                json={
                    "user_id": str(user_id),
                    "logical_model": "embed-test",
                    "inputs": ["hello", "world"],
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["vectors"]) == 2
        assert body["provider"] == "openai"
