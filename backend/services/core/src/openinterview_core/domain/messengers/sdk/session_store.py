"""Channel-agnostic mapping of (channel, external_id) -> user, and per-user
per-conversation active mentor/interviewer chat session.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import MessengerActiveSession, MessengerFilter, MessengerLink


def _whatsapp_phone_prefix_pattern(jid: str) -> str | None:
    """Build a SQL LIKE pattern that matches any device-suffixed JID for
    the same phone number. e.g. "15551234:5@s.whatsapp.net" ->
    "15551234%@s.whatsapp.net" — catches both "<phone>@..." and
    "<phone>:<n>@..." forms.
    """
    if "@" not in jid:
        return None
    local, _, host = jid.partition("@")
    phone = local.split(":", 1)[0]
    if not phone.isdigit():
        return None
    return f"{phone}%@{host}"


class MessengerLinkStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def link(
        self,
        *,
        user_id: UUID,
        channel: str,
        external_id: str,
        display_name: str | None = None,
    ) -> MessengerLink:
        """Insert or replace the link for this (channel, external_id)."""
        async with self._sm() as s:
            existing = (
                await s.execute(
                    select(MessengerLink).where(
                        MessengerLink.channel == channel,
                        MessengerLink.external_id == external_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.user_id = user_id
                if display_name is not None:
                    existing.display_name = display_name
                existing.last_seen_at = datetime.now(timezone.utc)
                # Re-pair = treat as fresh setup. Reset the filter mode AND
                # wipe any leftover rules so the user can't inadvertently
                # inherit stale allow/deny lists from a prior pair cycle.
                existing.filter_mode = "dms_only"
                await s.execute(
                    delete(MessengerFilter).where(
                        MessengerFilter.link_id == existing.id
                    )
                )
                row = existing
            else:
                row = MessengerLink(
                    user_id=user_id,
                    channel=channel,
                    external_id=external_id,
                    display_name=display_name,
                    last_seen_at=datetime.now(timezone.utc),
                )
                s.add(row)
            await s.commit()
            await s.refresh(row)
        return row

    async def resolve(self, *, channel: str, external_id: str) -> UUID | None:
        async with self._sm() as s:
            row = (
                await s.execute(
                    select(MessengerLink).where(
                        MessengerLink.channel == channel,
                        MessengerLink.external_id == external_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None and channel == "whatsapp":
                # Baileys appends a device-index suffix (":N") to the
                # owner's JID that may differ between pair sessions for
                # the same physical phone. Fall back to a phone-prefix
                # match so a previously-paired link still resolves after
                # a re-pair / restore on the same number.
                pat = _whatsapp_phone_prefix_pattern(external_id)
                if pat is not None:
                    row = (
                        await s.execute(
                            select(MessengerLink).where(
                                MessengerLink.channel == channel,
                                MessengerLink.external_id.like(pat),
                            )
                        )
                    ).scalars().first()
            if row is None:
                return None
            row.last_seen_at = datetime.now(timezone.utc)
            await s.commit()
            return row.user_id

    async def list_for_user(self, *, user_id: UUID) -> list[MessengerLink]:
        async with self._sm() as s:
            return list(
                (
                    await s.execute(
                        select(MessengerLink).where(MessengerLink.user_id == user_id)
                    )
                ).scalars()
            )

    async def unlink(self, *, user_id: UUID, link_id: UUID) -> bool:
        async with self._sm() as s:
            row = await s.get(MessengerLink, link_id)
            if row is None or row.user_id != user_id:
                return False
            await s.delete(row)
            await s.commit()
        return True


class ActiveSessionStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def get(
        self, *, user_id: UUID, channel: str, conversation_id: str | None
    ) -> MessengerActiveSession | None:
        async with self._sm() as s:
            return (
                await s.execute(
                    select(MessengerActiveSession).where(
                        MessengerActiveSession.user_id == user_id,
                        MessengerActiveSession.channel == channel,
                        MessengerActiveSession.conversation_id == conversation_id,
                    )
                )
            ).scalar_one_or_none()

    async def set(
        self,
        *,
        user_id: UUID,
        channel: str,
        conversation_id: str | None,
        chat_session_id: UUID,
        mode: str,
    ) -> None:
        async with self._sm() as s:
            existing = (
                await s.execute(
                    select(MessengerActiveSession).where(
                        MessengerActiveSession.user_id == user_id,
                        MessengerActiveSession.channel == channel,
                        MessengerActiveSession.conversation_id == conversation_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.conversation_id = conversation_id
                existing.chat_session_id = chat_session_id
                existing.mode = mode
            else:
                s.add(
                    MessengerActiveSession(
                        user_id=user_id,
                        channel=channel,
                        conversation_id=conversation_id,
                        chat_session_id=chat_session_id,
                        mode=mode,
                    )
                )
            await s.commit()

    async def clear(
        self, *, user_id: UUID, channel: str, conversation_id: str | None
    ) -> None:
        async with self._sm() as s:
            await s.execute(
                delete(MessengerActiveSession).where(
                    MessengerActiveSession.user_id == user_id,
                    MessengerActiveSession.channel == channel,
                    MessengerActiveSession.conversation_id == conversation_id,
                )
            )
            await s.commit()
