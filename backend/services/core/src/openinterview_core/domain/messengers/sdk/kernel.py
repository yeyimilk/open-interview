"""Kernel — channel-agnostic dispatch for inbound messenger turns.

Plugins parse webhook payloads into `InboundTurn`s and call
`MessengerKernel.handle_turn(plugin, turn)`. The kernel resolves the
remote user, parses the command grammar, drives mentor/interviewer
sessions through the `AgentFacade`, and sends replies back via
`delivery.deliver`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from openinterview_logging import get_logger

from . import command_parser as cmd
from .agent_facade import AgentFacade
from .command_parser import HELP_TEXT
from .delivery_guard import DeliveryGuard
from .filter_store import MessengerFilterStore, apply_filter
from .pair_tokens import PairTokenError, PairTokenStore
from .plugin import MessengerPlugin
from .session_store import ActiveSessionStore, MessengerLinkStore
from .types import InboundTurn


def _reply_to(turn: InboundTurn) -> str:
    """Where outbound replies should be addressed.

    For DMs this is the sender; for group messages we reply *into the
    group* (so the conversation reads naturally to other members).
    """
    return turn.chat_id or turn.external_user_id

log = get_logger(__name__)


# Narrow protocol for inbound idempotency so we can swap in an in-memory
# implementation in tests.
@dataclass(slots=True)
class _Dedup:
    seen: set[str]

    async def already_seen(self, channel: str, message_id: str) -> bool:
        key = f"{channel}:{message_id}"
        if key in self.seen:
            return True
        self.seen.add(key)
        return False


class InMemoryDedup(_Dedup):
    def __init__(self) -> None:
        super().__init__(seen=set())


class MessengerKernel:
    def __init__(
        self,
        *,
        agent: AgentFacade,
        links: MessengerLinkStore,
        active: ActiveSessionStore,
        pair_tokens: PairTokenStore,
        dedup: object | None = None,
        filters: MessengerFilterStore | None = None,
        delivery_guard: DeliveryGuard | None = None,
    ) -> None:
        self._agent = agent
        self._links = links
        self._active = active
        self._tokens = pair_tokens
        self._dedup = dedup or InMemoryDedup()
        self._filters = filters
        # Default safety net: 1 msg/s per recipient, burst 5, suppress
        # exact repeats within the last 3 sends, ~2k chars per chunk.
        self._guard = delivery_guard or DeliveryGuard(
            rate_per_second=1.0,
            burst=5,
            recent_window=3,
            chunk_pause_s=0.4,
            max_chars_per_chunk=2000,
        )

    async def _deliver(
        self,
        plugin: MessengerPlugin,
        *,
        to: str,
        text: str,
        idempotency_key: str | None = None,
    ):
        # Single chokepoint for outbound. Any send that bypasses this
        # loses the rate-limit + repeat-suppression + chunk-pacing
        # protections, so we keep the kernel's own paths funneling here.
        return await self._guard.deliver(
            plugin, to=to, text=text, idempotency_key=idempotency_key
        )

    async def handle_turn(
        self, plugin: MessengerPlugin, turn: InboundTurn
    ) -> None:
        """Route an inbound turn through (parse → resolve → filter → reply).

        Reply policy:
          Slash-commands always reply (they are an explicit address).
          Plain text in a DM with an active session → that session's agent.
          Plain text in a DM without a session → default chat agent
              (auto-created mentor-without-project, persisted as active).
          Plain text in a GROUP without a session → silent.
          Plain text in a GROUP with a session → that session's agent.
        """
        msg_id = turn.message_id or hashlib.sha256(
            f"{turn.external_user_id}|{turn.text}|{turn.received_at.isoformat()}".encode()
        ).hexdigest()
        if await self._dedup.already_seen(turn.channel, msg_id):
            log.info("messenger_inbound_dedup_skip", channel=turn.channel)
            return

        parsed = cmd.parse(turn.text)
        log.info(
            "messenger_inbound",
            channel=turn.channel,
            external_id_hash=hashlib.sha256(turn.external_user_id.encode()).hexdigest()[:8],
            kind=parsed.kind,
            is_group=turn.is_group,
        )

        # /link is the only command that works pre-binding.
        if parsed.kind == "link":
            await self._cmd_link(plugin, turn, parsed.args.get("token", ""))
            return

        link_external = turn.link_external_id or turn.external_user_id
        user_id = await self._links.resolve(
            channel=turn.channel, external_id=link_external
        )
        if user_id is None:
            # Unlinked + group → silent. Unlinked + DM → onboarding.
            if not turn.is_group:
                await self._deliver(
                    plugin,
                    to=_reply_to(turn),
                    text=(
                        "This account isn't linked yet. Open the web app, "
                        "go to Settings → Messaging, and scan the QR code."
                    ),
                )
            return

        if self._filters is not None:
            flt = await self._filters.load_for_channel_external(
                channel=turn.channel, external_id=link_external
            )
            if flt is not None and not apply_filter(
                flt=flt,
                sender_jid=turn.external_user_id,
                chat_jid=turn.chat_id or turn.external_user_id,
                is_group=turn.is_group,
            ):
                log.info(
                    "messenger_inbound_filtered",
                    channel=turn.channel, is_group=turn.is_group,
                )
                return

        # --- explicit commands -------------------------------------------
        if parsed.kind == "help":
            reason = parsed.args.get("reason")
            text = HELP_TEXT if reason is None else f"{reason}\n\n{HELP_TEXT}"
            await self._deliver(plugin, to=_reply_to(turn), text=text)
            return
        if parsed.kind == "status":
            await self._cmd_status(plugin, turn, user_id)
            return
        if parsed.kind == "mentor":
            await self._cmd_mentor(plugin, turn, user_id, parsed.args.get("project"))
            return
        if parsed.kind == "interview":
            await self._cmd_interview(plugin, turn, user_id, parsed.args)
            return
        if parsed.kind == "end":
            await self._cmd_end(plugin, turn, user_id)
            return
        if parsed.kind == "chat":
            await self._cmd_chat(plugin, turn, user_id)
            return
        if parsed.kind == "projects":
            await self._cmd_projects(plugin, turn, user_id)
            return
        if parsed.kind == "resumes":
            await self._cmd_resumes(plugin, turn, user_id)
            return
        if parsed.kind == "resume_show":
            await self._cmd_resume_show(
                plugin, turn, user_id, parsed.args.get("target", "")
            )
            return
        if parsed.kind == "sessions":
            await self._cmd_sessions(plugin, turn, user_id)
            return
        if parsed.kind == "resume_session":
            await self._cmd_resume_session(
                plugin, turn, user_id, parsed.args.get("target", "")
            )
            return
        if parsed.kind == "whoami":
            await self._cmd_whoami(plugin, turn, user_id)
            return

        # --- plain message routing ---------------------------------------
        active = await self._active.get(user_id=user_id, channel=turn.channel)
        if active is not None:
            # Already in a mode — route to its agent.
            await self._dispatch_message(plugin, turn, user_id, active)
            return
        if turn.is_group:
            # No mode + group: stay silent. The bot is "lurking" and only
            # answers when the owner explicitly addresses it via /mentor
            # or /interview etc.
            log.info("messenger_group_idle_skip", channel=turn.channel)
            return
        # No mode + DM: auto-start a default chat session so users don't
        # have to type /mentor first. They can switch with /interview or
        # bail with /exit at any time.
        await self._auto_start_chat_and_reply(plugin, turn, user_id)

    # ---- handlers ---------------------------------------------------------

    async def _cmd_link(
        self, plugin: MessengerPlugin, turn: InboundTurn, token: str
    ) -> None:
        if not token:
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text=(
                    "Usage: /link <token>\n"
                    "Open Settings → Messaging in the web app and scan the QR."
                ),
            )
            return
        try:
            user_id = await self._tokens.redeem(channel=turn.channel, token=token)
        except PairTokenError as e:
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text=f"Couldn't link: {e}. Generate a fresh QR in the web app.",
            )
            return
        await self._links.link(
            user_id=user_id,
            channel=turn.channel,
            external_id=turn.external_user_id,
            display_name=turn.sender_display_name,
        )
        await self._deliver(
            plugin,
            to=_reply_to(turn),
            text=(
                "Linked. Try:\n"
                "  /mentor                    — chat with the mentor\n"
                "  /interview <project> mid  — start a mock interview\n"
                "  /help                      — full command list"
            ),
        )

    async def _cmd_status(
        self, plugin: MessengerPlugin, turn: InboundTurn, user_id: UUID
    ) -> None:
        active = await self._active.get(user_id=user_id, channel=turn.channel)
        if active is None:
            text = (
                "No mode active. Send any message to start chatting, or:\n"
                "  /mentor [project]              enter mentor mode\n"
                "  /interview <project> <level>   enter interviewer mode"
            )
        else:
            label = {
                "chat": "general chat",
                "general": "general chat",
                "mentor": "mentor",
                "interviewer": "interviewer",
            }.get(active.mode, active.mode)
            text = (
                f"Currently in {label} mode "
                f"(session {str(active.chat_session_id)[:8]}). "
                "Use /exit to leave."
            )
        await self._deliver(plugin, to=_reply_to(turn), text=text)

    async def _cmd_mentor(
        self,
        plugin: MessengerPlugin,
        turn: InboundTurn,
        user_id: UUID,
        project: str | None,
    ) -> None:
        project_id = await self._agent.resolve_project_id(
            user_id=user_id, name_or_id=project
        )
        sid, opening = await self._agent.start_mentor_session(
            user_id=user_id, project_id=project_id
        )
        await self._active.set(
            user_id=user_id, channel=turn.channel, chat_session_id=sid, mode="mentor"
        )
        await self._deliver(
            plugin, to=_reply_to(turn), text=opening or "Mentor mode. Ask away."
        )

    async def _cmd_interview(
        self,
        plugin: MessengerPlugin,
        turn: InboundTurn,
        user_id: UUID,
        args: dict[str, str],
    ) -> None:
        project = args.get("project")
        level = args.get("level", "mid")
        if not project:
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text=(
                    "Usage: /interview <project> <level>\n"
                    "Levels: junior | mid | senior | lead"
                ),
            )
            return
        project_id = await self._agent.resolve_project_id(
            user_id=user_id, name_or_id=project
        )
        if project_id is None:
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text=f"Project '{project}' not found. Upload one in the web app first.",
            )
            return
        sid, first_q = await self._agent.start_interview_session(
            user_id=user_id,
            project_id=project_id,
            position="swe_generic",
            level=level,
        )
        await self._active.set(
            user_id=user_id,
            channel=turn.channel,
            chat_session_id=sid,
            mode="interviewer",
        )
        await self._deliver(
            plugin,
            to=_reply_to(turn),
            text=f"Interview started ({level}).\n\n{first_q}",
        )

    async def _cmd_end(
        self, plugin: MessengerPlugin, turn: InboundTurn, user_id: UUID
    ) -> None:
        active = await self._active.get(user_id=user_id, channel=turn.channel)
        if active is None:
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text="You're not in any mode right now.",
            )
            return
        # General/chat modes don't need a fancy summary — just clear them.
        if active.mode in ("chat", "general"):
            await self._active.clear(user_id=user_id, channel=turn.channel)
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text=(
                    "Left chat mode. Send any message to start again, or "
                    "use /mentor or /interview to enter a specific mode."
                ),
            )
            return
        summary = await self._agent.end_session(
            user_id=user_id, session_id=active.chat_session_id, mode=active.mode
        )
        await self._active.clear(user_id=user_id, channel=turn.channel)
        await self._deliver(plugin, to=_reply_to(turn), text=summary)

    async def _dispatch_message(
        self,
        plugin: MessengerPlugin,
        turn: InboundTurn,
        user_id: UUID,
        active,
    ) -> None:
        # `active` is the MessengerActiveSession row already loaded by
        # the caller. Route to the agent for the active mode.
        if active.mode == "interviewer":
            reply = await self._agent.send_interview_message(
                user_id=user_id, session_id=active.chat_session_id, content=turn.text
            )
        elif active.mode in ("general", "chat"):
            reply = await self._agent.send_general_message(
                user_id=user_id, session_id=active.chat_session_id, content=turn.text
            )
        else:  # mentor (project-scoped)
            reply = await self._agent.send_mentor_message(
                user_id=user_id, session_id=active.chat_session_id, content=turn.text
            )
        await self._deliver(plugin, to=_reply_to(turn), text=reply)

    async def _auto_start_chat_and_reply(
        self, plugin: MessengerPlugin, turn: InboundTurn, user_id: UUID
    ) -> None:
        """First plain DM after pairing — auto-spin a /chat (general) session
        so the user isn't yelled at to run a slash command first."""
        sid, opening = await self._agent.start_general_session(user_id=user_id)
        await self._active.set(
            user_id=user_id,
            channel=turn.channel,
            chat_session_id=sid,
            mode="general",
        )
        reply = await self._agent.send_general_message(
            user_id=user_id, session_id=sid, content=turn.text
        )
        # Combine opening line with the first response, but only the first
        # time. After this, plain messages route via _dispatch_message.
        text = reply
        if opening:
            text = f"{opening}\n\n{reply}"
        await self._deliver(plugin, to=_reply_to(turn), text=text)

    # ---- new commands ----------------------------------------------------

    async def _cmd_chat(
        self, plugin: MessengerPlugin, turn: InboundTurn, user_id: UUID
    ) -> None:
        sid, opening = await self._agent.start_general_session(user_id=user_id)
        await self._active.set(
            user_id=user_id,
            channel=turn.channel,
            chat_session_id=sid,
            mode="general",
        )
        await self._deliver(
            plugin,
            to=_reply_to(turn),
            text=opening or "Chat mode is on. Ask anything.",
        )

    async def _cmd_projects(
        self, plugin: MessengerPlugin, turn: InboundTurn, user_id: UUID
    ) -> None:
        rows = await self._agent.list_projects(user_id=user_id)
        if not rows:
            text = "No projects yet. Upload one in the web app."
        else:
            lines = ["Your projects:"]
            for i, p in enumerate(rows, 1):
                lines.append(
                    f"  {i}. {p.name}  ({p.short_id}) · {p.status}"
                )
            text = "\n".join(lines)
        await self._deliver(plugin, to=_reply_to(turn), text=text)

    async def _cmd_resumes(
        self, plugin: MessengerPlugin, turn: InboundTurn, user_id: UUID
    ) -> None:
        rows = await self._agent.list_resumes(user_id=user_id)
        if not rows:
            text = "No resumes yet. Upload one in the web app."
        else:
            lines = ["Your resumes:"]
            for i, r in enumerate(rows, 1):
                lines.append(
                    f"  {i}. {r.filename}  ({r.short_id}) · "
                    f"{r.n_claims} claims, {r.n_mapped} mapped"
                )
            lines.append("\nUse /resume <name-or-id> for details.")
            text = "\n".join(lines)
        await self._deliver(plugin, to=_reply_to(turn), text=text)

    async def _cmd_resume_show(
        self,
        plugin: MessengerPlugin,
        turn: InboundTurn,
        user_id: UUID,
        target: str,
    ) -> None:
        if not target:
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text="Usage: /resume <name-or-id>. Use /resumes to list.",
            )
            return
        text = await self._agent.get_resume_detail(
            user_id=user_id, name_or_id=target
        )
        if text is None:
            text = f"No resume matching '{target}'. Try /resumes."
        await self._deliver(plugin, to=_reply_to(turn), text=text)

    async def _cmd_sessions(
        self, plugin: MessengerPlugin, turn: InboundTurn, user_id: UUID
    ) -> None:
        rows = await self._agent.list_sessions(user_id=user_id)
        if not rows:
            text = "No sessions yet. Try /mentor or /interview to start one."
        else:
            lines = ["Recent sessions:"]
            for i, s in enumerate(rows, 1):
                proj = f" [{s.project_name}]" if s.project_name else ""
                lines.append(
                    f"  {i}. {s.mode}{proj} · {s.turn_count} turns · "
                    f"{s.age_human} · ({s.short_id}) · {s.status}"
                )
            lines.append("\nUse /resume-session <id-prefix> to continue one.")
            text = "\n".join(lines)
        await self._deliver(plugin, to=_reply_to(turn), text=text)

    async def _cmd_resume_session(
        self,
        plugin: MessengerPlugin,
        turn: InboundTurn,
        user_id: UUID,
        target: str,
    ) -> None:
        if not target:
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text=(
                    "Usage: /resume-session <id-prefix>. "
                    "Use /sessions to see ids."
                ),
            )
            return
        result = await self._agent.resume_session(
            user_id=user_id, id_prefix=target
        )
        if result is None:
            await self._deliver(
                plugin,
                to=_reply_to(turn),
                text=f"No session matching '{target}'. Try /sessions.",
            )
            return
        sid, mode, opener = result
        # Don't switch to ended sessions; tell the user.
        if "already ended" in opener:
            await self._deliver(plugin, to=_reply_to(turn), text=opener)
            return
        await self._active.set(
            user_id=user_id,
            channel=turn.channel,
            chat_session_id=sid,
            mode=mode,
        )
        await self._deliver(plugin, to=_reply_to(turn), text=opener)

    async def _cmd_whoami(
        self, plugin: MessengerPlugin, turn: InboundTurn, user_id: UUID
    ) -> None:
        c = await self._agent.whoami_counts(user_id=user_id)
        text = (
            "Workspace summary:\n"
            f"  Projects:        {c.get('projects', 0)}\n"
            f"  Resumes:         {c.get('resumes', 0)}\n"
            f"  Sessions total:  {c.get('sessions_total', 0)}\n"
            f"  Sessions active: {c.get('sessions_active', 0)}"
        )
        await self._deliver(plugin, to=_reply_to(turn), text=text)
