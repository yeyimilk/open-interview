"""Per-link conversation filter store.

A `MessengerLink` has a `filter_mode` plus zero or more `MessengerFilter`
rows. `apply_filter` decides whether an incoming turn (DM or group) is
allowed through.

Modes:
  dms_only  — pass only 1:1 chats whose sender is the linked owner.
              (Sender phone is matched against the owner's phone number,
              which is stored as `display_name` at pairing time.)
  allowlist — pass turns matching ANY rule.
  denylist  — pass turns NOT matching any rule.
  all       — pass everything.

Rule kinds:
  phone — matches if the sender's phone (digits only) equals `value`.
  group — matches if the chat is a group with JID equal to `value`.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from openinterview_db import MessengerFilter, MessengerLink


@dataclass(slots=True)
class FilterRule:
    id: UUID
    kind: str  # "phone" | "group"
    value: str
    label: str | None


@dataclass(slots=True)
class LinkFilter:
    mode: str
    rules: list[FilterRule]
    owner_phone: str | None  # used in dms_only mode


def _digits(s: str | None) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _jid_to_phone(jid: str) -> str:
    # "15551234567:3@s.whatsapp.net" or "15551234567@s.whatsapp.net" -> "15551234567"
    local = jid.split("@", 1)[0]
    return _digits(local.split(":", 1)[0])


class MessengerFilterStore:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker

    async def load(self, *, link_id: UUID) -> LinkFilter | None:
        async with self._sm() as s:
            link = (
                await s.execute(select(MessengerLink).where(MessengerLink.id == link_id))
            ).scalar_one_or_none()
            if link is None:
                return None
            rows = (
                await s.execute(
                    select(MessengerFilter).where(MessengerFilter.link_id == link_id)
                )
            ).scalars().all()
            return LinkFilter(
                mode=link.filter_mode or "dms_only",
                rules=[
                    FilterRule(id=r.id, kind=r.kind, value=r.value, label=r.label)
                    for r in rows
                ],
                owner_phone=_digits(link.display_name),
            )

    async def load_for_channel_external(
        self, *, channel: str, external_id: str
    ) -> LinkFilter | None:
        async with self._sm() as s:
            link = (
                await s.execute(
                    select(MessengerLink).where(
                        MessengerLink.channel == channel,
                        MessengerLink.external_id == external_id,
                    )
                )
            ).scalar_one_or_none()
            if link is None and channel == "whatsapp":
                # Phone-prefix fallback (see MessengerLinkStore.resolve).
                if "@" in external_id:
                    local, _, host = external_id.partition("@")
                    phone = local.split(":", 1)[0]
                    if phone.isdigit():
                        link = (
                            await s.execute(
                                select(MessengerLink).where(
                                    MessengerLink.channel == channel,
                                    MessengerLink.external_id.like(
                                        f"{phone}%@{host}"
                                    ),
                                )
                            )
                        ).scalars().first()
            if link is None:
                return None
            return await self.load(link_id=link.id)

    async def set_mode(self, *, link_id: UUID, mode: str) -> None:
        if mode not in {"dms_only", "allowlist", "denylist", "all"}:
            raise ValueError(f"invalid filter mode: {mode}")
        async with self._sm() as s:
            link = (
                await s.execute(select(MessengerLink).where(MessengerLink.id == link_id))
            ).scalar_one_or_none()
            if link is None:
                raise LookupError("link not found")
            link.filter_mode = mode
            await s.commit()

    async def replace_rules(
        self,
        *,
        link_id: UUID,
        rules: list[tuple[str, str, str | None]],  # (kind, value, label)
    ) -> list[FilterRule]:
        async with self._sm() as s:
            await s.execute(delete(MessengerFilter).where(MessengerFilter.link_id == link_id))
            seen: set[tuple[str, str]] = set()
            for kind, value, label in rules:
                value_norm = _digits(value) if kind == "phone" else value.strip()
                if not value_norm:
                    continue
                k = (kind, value_norm)
                if k in seen:
                    continue
                seen.add(k)
                s.add(
                    MessengerFilter(
                        link_id=link_id, kind=kind, value=value_norm, label=label
                    )
                )
            await s.commit()
            rows = (
                await s.execute(
                    select(MessengerFilter).where(MessengerFilter.link_id == link_id)
                )
            ).scalars().all()
            return [
                FilterRule(id=r.id, kind=r.kind, value=r.value, label=r.label)
                for r in rows
            ]


def apply_filter(
    *,
    flt: LinkFilter,
    sender_jid: str,
    chat_jid: str,
    is_group: bool,
) -> bool:
    """Return True iff the turn passes the filter (i.e. should be processed)."""
    sender_phone = _jid_to_phone(sender_jid)
    if flt.mode == "all":
        return True
    if flt.mode == "dms_only":
        if is_group:
            return False
        # Allow any DM whose sender is the linked owner. We compare phones
        # because Baileys appends ":N" device indices to the owner's JID.
        if not flt.owner_phone:
            return True
        return sender_phone == flt.owner_phone
    if flt.mode in ("allowlist", "denylist"):
        match = False
        for r in flt.rules:
            if r.kind == "phone" and sender_phone == _digits(r.value):
                match = True
                break
            if r.kind == "group" and is_group and chat_jid == r.value:
                match = True
                break
        return match if flt.mode == "allowlist" else not match
    return True
