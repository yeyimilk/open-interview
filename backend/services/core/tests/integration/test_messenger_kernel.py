"""Kernel-level integration test using a fake plugin and a fake agent
facade. Verifies the full inbound dispatch path:

  /link <token>            → binds (channel, external_id) to a user
  unlinked plain message   → bot tells the user to scan QR
  /mentor                  → starts mentor session, opening message sent
  plain message after that → routed to mentor
  /interview [target] [lvl] → starts interview (resume-driven by default;
                              `--project` opts into legacy project mode)
  /end                     → ends session, summary sent
"""
from __future__ import annotations

import os
import uuid

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from openinterview_core.domain.messengers.sdk import command_parser as cp  # noqa: F401  (sanity)
from openinterview_core.domain.messengers.sdk.kernel import MessengerKernel
from openinterview_core.domain.messengers.sdk.pair_tokens import PairTokenStore
from openinterview_core.domain.messengers.sdk.plugin import (
    MessengerCapabilities,
    MessengerIdentity,
)
from openinterview_core.domain.messengers.sdk.session_store import (
    ActiveSessionStore,
    MessengerLinkStore,
)
from openinterview_core.domain.messengers.sdk.types import InboundTurn
from openinterview_db import Base, User


# ---- fakes ----------------------------------------------------------------


class FakeAgentFacade:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.next_session_id = uuid.uuid4()

    async def resolve_project_id(self, *, user_id, name_or_id):
        self.calls.append(("resolve_project_id", {"user_id": user_id, "name": name_or_id}))
        if name_or_id and name_or_id.lower() == "unknown":
            return None
        return uuid.uuid4()

    async def resolve_resume_id(self, *, user_id, name_or_id):
        self.calls.append(("resolve_resume_id", {"user_id": user_id, "name": name_or_id}))
        if name_or_id and name_or_id.lower() in ("missing", "unknown"):
            return None
        return uuid.uuid4()

    async def start_mentor_session(self, *, user_id, project_id):
        self.calls.append(("start_mentor", {"user_id": user_id, "project_id": project_id}))
        sid = uuid.uuid4()
        self.next_session_id = sid
        return sid, "Mentor mode is on."

    async def send_mentor_message(self, *, user_id, session_id, content):
        self.calls.append(("send_mentor", {"user_id": user_id, "content": content}))
        return f"mentor-reply:{content}"

    async def start_interview_session(self, *, user_id, project_id, position, level):
        self.calls.append(("start_interview", {"level": level, "project_id": project_id}))
        sid = uuid.uuid4()
        self.next_session_id = sid
        return sid, "Question 1: Tell me about your project."

    async def start_interview_session_for_resume(
        self, *, user_id, resume_id, position, level
    ):
        self.calls.append(
            ("start_interview_resume", {"level": level, "resume_id": resume_id})
        )
        sid = uuid.uuid4()
        self.next_session_id = sid
        return sid, "Question 1: Walk me through your latency win."

    async def send_interview_message(self, *, user_id, session_id, content):
        self.calls.append(("send_interview", {"content": content}))
        return f"interview-reply:{content}"

    async def end_session(self, *, user_id, session_id, mode):
        self.calls.append(("end", {"mode": mode}))
        return f"{mode} ended."

    # ---- general /chat mode ------------------------------------------
    async def start_general_session(self, *, user_id):
        self.calls.append(("start_general", {"user_id": user_id}))
        sid = uuid.uuid4()
        self.next_session_id = sid
        return sid, "Chat mode is on."

    async def send_general_message(self, *, user_id, session_id, content):
        self.calls.append(("send_general", {"content": content}))
        return f"general-reply:{content}"

    # ---- workspace introspection -------------------------------------
    async def list_projects(self, *, user_id, limit=10):
        from openinterview_core.domain.messengers.sdk.agent_facade import (
            ProjectBrief,
        )
        self.calls.append(("list_projects", {}))
        return [
            ProjectBrief(
                id=uuid.uuid4(), name="demo", status="ready", short_id="abcdef12"
            )
        ]

    async def list_resumes(self, *, user_id, limit=10):
        from openinterview_core.domain.messengers.sdk.agent_facade import (
            ResumeBrief,
        )
        self.calls.append(("list_resumes", {}))
        return [
            ResumeBrief(
                id=uuid.uuid4(),
                filename="r.pdf",
                n_claims=3,
                n_mapped=1,
                short_id="11223344",
            )
        ]

    async def get_resume_detail(self, *, user_id, name_or_id):
        self.calls.append(("get_resume_detail", {"target": name_or_id}))
        if name_or_id == "missing":
            return None
        return f"Resume: {name_or_id}\nSkills: x, y"

    async def list_sessions(self, *, user_id, limit=10):
        from openinterview_core.domain.messengers.sdk.agent_facade import (
            SessionBrief,
        )
        self.calls.append(("list_sessions", {}))
        return [
            SessionBrief(
                id=uuid.uuid4(),
                mode="mentor",
                project_name="demo",
                turn_count=4,
                status="active",
                age_human="2h ago",
                short_id="aabbccdd",
            )
        ]

    async def resume_session(self, *, user_id, id_prefix):
        self.calls.append(("resume_session", {"prefix": id_prefix}))
        if id_prefix == "missing":
            return None
        sid = uuid.uuid4()
        return sid, "mentor", f"Resumed mentor session ({id_prefix})."

    async def whoami_counts(self, *, user_id):
        self.calls.append(("whoami_counts", {}))
        return {
            "projects": 2,
            "resumes": 1,
            "sessions_total": 5,
            "sessions_active": 1,
        }


class FakePlugin:
    def __init__(self) -> None:
        self.identity = MessengerIdentity(id="fakeapp", name="FakeApp")
        self.capabilities = MessengerCapabilities(max_outbound_chars=200)
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, *, to, text, idempotency_key=None):
        self.sent.append((to, text))


# ---- fixtures -------------------------------------------------------------


@pytest.fixture()
async def env(tmp_path):
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    db_path = tmp_path / "messengers.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    # Seed user.
    user_id = uuid.uuid4()
    async with sm() as s:
        s.add(User(id=user_id, email="u@x.com", password_hash="x", display_name="U"))
        await s.commit()

    facade = FakeAgentFacade()
    kernel = MessengerKernel(
        agent=facade,
        links=MessengerLinkStore(sm),
        active=ActiveSessionStore(sm),
        pair_tokens=PairTokenStore(sm),
    )
    plugin = FakePlugin()

    yield {
        "kernel": kernel,
        "plugin": plugin,
        "facade": facade,
        "sm": sm,
        "user_id": user_id,
    }
    await engine.dispose()


def _turn(text: str, *, external_id: str = "+15551234567", msg_id: str | None = None) -> InboundTurn:
    return InboundTurn(
        channel="fakeapp",
        external_user_id=external_id,
        text=text,
        message_id=msg_id,
    )


# ---- tests ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlinked_user_gets_pairing_prompt(env):
    await env["kernel"].handle_turn(env["plugin"], _turn("hello"))
    assert env["plugin"].sent
    assert "Settings" in env["plugin"].sent[0][1]
    assert env["plugin"].sent[0][1].count("scan") >= 1 or "QR" in env["plugin"].sent[0][1]


@pytest.mark.asyncio
async def test_link_redeems_token_then_mentor_works(env):
    # Mint a token for the user.
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")

    # Send /link <token>.
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="m1"))
    assert any("Linked" in s[1] for s in env["plugin"].sent)

    # /mentor should now start a session and send the opener.
    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("/mentor", msg_id="m2"))
    assert any("Mentor mode" in s[1] for s in env["plugin"].sent)
    assert any(c[0] == "start_mentor" for c in env["facade"].calls)

    # Plain message → routed to mentor.
    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("how should I architect this", msg_id="m3")
    )
    assert any("mentor-reply" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_link_with_bad_token_rejects(env):
    await env["kernel"].handle_turn(env["plugin"], _turn("/link nope", msg_id="m1"))
    assert any("Couldn't link" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_interview_flow_resume_default(env):
    """`/interview <target> <level>` is now resume-driven by default."""
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="m1"))

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/interview ada.pdf senior", msg_id="m2")
    )
    assert any("Question 1" in s[1] for s in env["plugin"].sent)
    assert any("resume-driven" in s[1] for s in env["plugin"].sent)
    assert any(
        c[0] == "start_interview_resume" and c[1]["level"] == "senior"
        for c in env["facade"].calls
    )

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("My answer is X.", msg_id="m3"))
    assert any("interview-reply" in s[1] for s in env["plugin"].sent)

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("/end", msg_id="m4"))
    assert any("interviewer ended" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_interview_bare_uses_latest_resume(env):
    """`/interview` with no args resolves the latest resume."""
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="m1"))

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/interview", msg_id="m2")
    )
    # FakeAgentFacade.resolve_resume_id returns a uuid for None target.
    assert any(
        c[0] == "resolve_resume_id" and c[1]["name"] is None
        for c in env["facade"].calls
    )
    assert any(c[0] == "start_interview_resume" for c in env["facade"].calls)


@pytest.mark.asyncio
async def test_interview_project_flag_uses_legacy_path(env):
    """`--project demo` opts into the legacy single-project flow."""
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="m1"))

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/interview --project demo mid", msg_id="m2")
    )
    assert any("project mode" in s[1] for s in env["plugin"].sent)
    assert any(c[0] == "start_interview" for c in env["facade"].calls)
    # The resume resolver wasn't consulted at all on this path.
    assert not any(c[0] == "resolve_resume_id" for c in env["facade"].calls)


@pytest.mark.asyncio
async def test_interview_with_unknown_resume_fails_gracefully(env):
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="m1"))

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/interview missing mid", msg_id="m2")
    )
    assert any("not found" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_interview_with_unknown_project_fails_gracefully(env):
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="m1"))

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/interview --project unknown mid", msg_id="m2")
    )
    assert any("not found" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_inbound_dedup_ignores_repeats(env):
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="dup"))
    env["plugin"].sent.clear()
    # Same message_id twice → second call should be a no-op.
    await env["kernel"].handle_turn(env["plugin"], _turn("/mentor", msg_id="K"))
    first_calls = list(env["facade"].calls)
    await env["kernel"].handle_turn(env["plugin"], _turn("/mentor", msg_id="K"))
    assert env["facade"].calls == first_calls


@pytest.mark.asyncio
async def test_help_text_lists_commands(env):
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}"))
    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("/help"))
    joined = "\n".join(s[1] for s in env["plugin"].sent)
    assert "/mentor" in joined
    assert "/interview" in joined
    assert "/exit" in joined  # /end is renamed to /exit (with /end/stop/quit aliases)


@pytest.mark.asyncio
async def test_status_reports_active_session(env):
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="a"))
    await env["kernel"].handle_turn(env["plugin"], _turn("/mentor", msg_id="b"))
    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("/status", msg_id="c"))
    assert any("mentor mode" in s[1] for s in env["plugin"].sent)


# ---- new dispatch policy --------------------------------------------------


def _group_turn(text: str, *, msg_id: str | None = None) -> InboundTurn:
    return InboundTurn(
        channel="fakeapp",
        external_user_id="+15555550000",
        text=text,
        message_id=msg_id,
        chat_id="100-200@g.us",
        is_group=True,
        link_external_id="+15551234567",
    )


@pytest.mark.asyncio
async def test_plain_dm_without_session_auto_starts_chat_and_replies(env):
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="m1"))

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("hello!", msg_id="m2"))
    # No nag, AND the user got an actual /chat (general) reply.
    joined = "\n".join(s[1] for s in env["plugin"].sent)
    assert "No active session" not in joined
    assert "general-reply:hello!" in joined
    # The general session is now persisted; second message routes to it.
    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("again", msg_id="m3"))
    assert any("general-reply:again" in s[1] for s in env["plugin"].sent)
    assert sum(1 for c in env["facade"].calls if c[0] == "start_general") == 1


@pytest.mark.asyncio
async def test_plain_group_message_without_session_is_silent(env):
    # We don't even need a link in DB for this user — group messages
    # without an active session must never produce output.
    await env["kernel"].handle_turn(env["plugin"], _group_turn("random chatter", msg_id="g1"))
    assert env["plugin"].sent == []


@pytest.mark.asyncio
async def test_exit_alias_clears_chat_mode(env):
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(env["plugin"], _turn(f"/link {token}", msg_id="m1"))
    # Auto-starts chat mode.
    await env["kernel"].handle_turn(env["plugin"], _turn("hi", msg_id="m2"))

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("/exit", msg_id="m3"))
    joined = "\n".join(s[1] for s in env["plugin"].sent)
    assert "Left chat mode" in joined

    # After /exit, status should show "no mode active".
    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("/status", msg_id="m4"))
    assert any("No mode active" in s[1] for s in env["plugin"].sent)


# ---- workspace commands ---------------------------------------------------


async def _link(env, msg_id="link-base"):
    store = PairTokenStore(env["sm"])
    token, _ = await store.mint(user_id=env["user_id"], channel="fakeapp")
    await env["kernel"].handle_turn(
        env["plugin"], _turn(f"/link {token}", msg_id=msg_id)
    )
    env["plugin"].sent.clear()


@pytest.mark.asyncio
async def test_chat_command_starts_general_mode(env):
    await _link(env)
    await env["kernel"].handle_turn(env["plugin"], _turn("/chat", msg_id="c1"))
    assert any("Chat mode" in s[1] for s in env["plugin"].sent)
    assert any(c[0] == "start_general" for c in env["facade"].calls)

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("hello", msg_id="c2"))
    assert any("general-reply:hello" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_projects_command_lists(env):
    await _link(env)
    await env["kernel"].handle_turn(env["plugin"], _turn("/projects", msg_id="p1"))
    joined = "\n".join(s[1] for s in env["plugin"].sent)
    assert "demo" in joined
    assert "abcdef12" in joined


@pytest.mark.asyncio
async def test_resumes_and_resume_show(env):
    await _link(env)
    await env["kernel"].handle_turn(env["plugin"], _turn("/resumes", msg_id="r1"))
    assert any("r.pdf" in s[1] for s in env["plugin"].sent)

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/resume r.pdf", msg_id="r2")
    )
    assert any("Skills" in s[1] for s in env["plugin"].sent)

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/resume missing", msg_id="r3")
    )
    assert any("No resume matching" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_sessions_and_resume_session(env):
    await _link(env)
    await env["kernel"].handle_turn(env["plugin"], _turn("/sessions", msg_id="s1"))
    assert any("aabbccdd" in s[1] for s in env["plugin"].sent)

    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/resume-session aabbccdd", msg_id="s2")
    )
    joined = "\n".join(s[1] for s in env["plugin"].sent)
    assert "Resumed mentor session" in joined

    # Plain message now routes to mentor (the resumed mode).
    env["plugin"].sent.clear()
    await env["kernel"].handle_turn(env["plugin"], _turn("ping", msg_id="s3"))
    assert any("mentor-reply:ping" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_resume_session_unknown_prefix(env):
    await _link(env)
    await env["kernel"].handle_turn(
        env["plugin"], _turn("/resume-session missing", msg_id="rs1")
    )
    assert any("No session matching" in s[1] for s in env["plugin"].sent)


@pytest.mark.asyncio
async def test_whoami_reports_counts(env):
    await _link(env)
    await env["kernel"].handle_turn(env["plugin"], _turn("/whoami", msg_id="w1"))
    joined = "\n".join(s[1] for s in env["plugin"].sent)
    assert "Projects" in joined
    assert "2" in joined  # projects count
    assert "Sessions" in joined
