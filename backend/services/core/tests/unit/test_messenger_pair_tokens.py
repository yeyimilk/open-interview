"""Pair token mint/redeem semantics."""
from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from openinterview_core.domain.messengers.sdk.pair_tokens import (
    PairTokenError,
    PairTokenStore,
)
from openinterview_db import Base, User


@pytest.fixture()
async def store_and_user(tmp_path):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path/'tok.sqlite'}", future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with sm() as s:
        s.add(User(id=user_id, email="t@x.com", password_hash="x", display_name="t"))
        await s.commit()
    yield PairTokenStore(sm), user_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_mint_and_redeem_happy_path(store_and_user):
    store, user_id = store_and_user
    token, expires = await store.mint(user_id=user_id, channel="whatsapp")
    assert token and len(token) >= 20
    redeemed_user_id = await store.redeem(channel="whatsapp", token=token)
    assert redeemed_user_id == user_id


@pytest.mark.asyncio
async def test_redeem_unknown_token_errors(store_and_user):
    store, _ = store_and_user
    with pytest.raises(PairTokenError):
        await store.redeem(channel="whatsapp", token="bogus")


@pytest.mark.asyncio
async def test_redeem_twice_fails(store_and_user):
    store, user_id = store_and_user
    token, _ = await store.mint(user_id=user_id, channel="whatsapp")
    await store.redeem(channel="whatsapp", token=token)
    with pytest.raises(PairTokenError):
        await store.redeem(channel="whatsapp", token=token)


@pytest.mark.asyncio
async def test_expired_token_rejected(store_and_user):
    store, user_id = store_and_user
    token, _ = await store.mint(
        user_id=user_id, channel="whatsapp", ttl=timedelta(seconds=-1)
    )
    with pytest.raises(PairTokenError):
        await store.redeem(channel="whatsapp", token=token)


@pytest.mark.asyncio
async def test_channel_isolation(store_and_user):
    store, user_id = store_and_user
    token, _ = await store.mint(user_id=user_id, channel="whatsapp")
    with pytest.raises(PairTokenError):
        await store.redeem(channel="telegram", token=token)
