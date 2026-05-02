"""Auto-title and rename behaviour for ChatSession.

The repo derives a short title from the first user message when the title
is still NULL, and exposes ``update_session_title`` so users can rename
or clear it later. We exercise both at the SQL layer with sqlite to keep
the tests fast and free of fixtures from the rest of the app.
"""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from openinterview_core.infra.db.chat_repository import (
    SqlChatRepository,
    _derive_title,
)
from openinterview_db import Base, User


# ---- pure helper ---------------------------------------------------------


def test_derive_title_short_input_unchanged():
    assert _derive_title("Hello there") == "Hello there"


def test_derive_title_collapses_whitespace_and_takes_first_line():
    assert (
        _derive_title("  hello\nthere   friend ")
        == "hello"
    )


def test_derive_title_strips_leading_slash_command():
    # Free-form chat shouldn't get titled "/help me debug" — drop the /.
    assert _derive_title("/help me debug").startswith("help me debug")


def test_derive_title_truncates_at_word_boundary_with_ellipsis():
    text = (
        "This is a fairly long opening message about Postgres replication "
        "and how to bootstrap a fresh follower from a base backup."
    )
    out = _derive_title(text, max_chars=40)
    assert len(out) <= 41  # 40 + ellipsis
    assert out.endswith("…")
    # We cut at a word boundary, so the last word before the ellipsis is whole.
    last = out[:-1].rstrip().split(" ")[-1]
    assert last in text


def test_derive_title_empty_falls_back_to_untitled():
    assert _derive_title("") == "Untitled"
    assert _derive_title("   ") == "Untitled"


# ---- repository round-trip ------------------------------------------------


@pytest.fixture()
async def repo_env(tmp_path):
    db_path = tmp_path / "chat_titles.sqlite"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with sm() as s:
        s.add(
            User(id=user_id, email="t@x.com", password_hash="x", display_name="T")
        )
        await s.commit()
    yield {"sm": sm, "user_id": user_id}
    await engine.dispose()


@pytest.mark.asyncio
async def test_first_user_message_auto_titles_session(repo_env):
    sm = repo_env["sm"]
    user_id = repo_env["user_id"]

    async with sm() as s:
        repo = SqlChatRepository(s)
        sess = await repo.create_session(
            user_id=user_id, mode="general", title=None
        )
        assert sess.title is None

        await repo.append_message(
            session_id=sess.id,
            user_id=user_id,
            role="user",
            content="How does Postgres logical replication actually work?",
        )

    async with sm() as s:
        sess2 = await SqlChatRepository(s).get_session(
            user_id=user_id, session_id=sess.id
        )
    assert sess2 is not None
    assert sess2.title == "How does Postgres logical replication actually work?"


@pytest.mark.asyncio
async def test_assistant_message_does_not_set_title(repo_env):
    sm = repo_env["sm"]
    user_id = repo_env["user_id"]
    async with sm() as s:
        repo = SqlChatRepository(s)
        sess = await repo.create_session(
            user_id=user_id, mode="general", title=None
        )
        await repo.append_message(
            session_id=sess.id,
            user_id=user_id,
            role="assistant",
            content="Sure, I can help with that.",
        )
    async with sm() as s:
        sess2 = await SqlChatRepository(s).get_session(
            user_id=user_id, session_id=sess.id
        )
    assert sess2 is not None
    assert sess2.title is None


@pytest.mark.asyncio
async def test_existing_title_is_not_overwritten(repo_env):
    sm = repo_env["sm"]
    user_id = repo_env["user_id"]
    async with sm() as s:
        repo = SqlChatRepository(s)
        sess = await repo.create_session(
            user_id=user_id, mode="interviewer", title="Mock interview (mid)"
        )
        await repo.append_message(
            session_id=sess.id,
            user_id=user_id,
            role="user",
            content="I'm ready, please start.",
        )
    async with sm() as s:
        sess2 = await SqlChatRepository(s).get_session(
            user_id=user_id, session_id=sess.id
        )
    assert sess2.title == "Mock interview (mid)"


@pytest.mark.asyncio
async def test_update_session_title_clears_with_none(repo_env):
    sm = repo_env["sm"]
    user_id = repo_env["user_id"]
    async with sm() as s:
        repo = SqlChatRepository(s)
        sess = await repo.create_session(
            user_id=user_id, mode="general", title="Initial"
        )

    async with sm() as s:
        repo = SqlChatRepository(s)
        updated = await repo.update_session_title(
            session_id=sess.id, user_id=user_id, title="Renamed!"
        )
        assert updated is not None
        assert updated.title == "Renamed!"

        cleared = await repo.update_session_title(
            session_id=sess.id, user_id=user_id, title=None
        )
        assert cleared is not None
        assert cleared.title is None

        # Empty string is treated as "clear".
        empty = await repo.update_session_title(
            session_id=sess.id, user_id=user_id, title="   "
        )
        assert empty is not None
        assert empty.title is None


@pytest.mark.asyncio
async def test_update_session_title_rejects_other_users_session(repo_env):
    sm = repo_env["sm"]
    user_id = repo_env["user_id"]
    async with sm() as s:
        repo = SqlChatRepository(s)
        sess = await repo.create_session(
            user_id=user_id, mode="general", title="Mine"
        )

    other = uuid.uuid4()
    async with sm() as s:
        out = await SqlChatRepository(s).update_session_title(
            session_id=sess.id, user_id=other, title="Hijacked"
        )
        assert out is None
