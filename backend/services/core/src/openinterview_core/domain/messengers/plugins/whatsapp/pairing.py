"""Tracks (pair_id → user_id) for in-flight WhatsApp pairings, so when the
bridge signals "paired" we know which app user to attach the new account
to.

In-memory by design: pairings are short-lived (<10 min) and a server
restart wipes them — the user just clicks "Connect" again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID


@dataclass(slots=True)
class _Entry:
    user_id: UUID
    expires_at: datetime
    account_id: str | None = None
    completed: bool = False


class WhatsAppPairingTracker:
    """Channel-specific shim — does NOT replace the channel-agnostic
    PairTokenStore in the SDK. It only owns the bridge-side pair_id ↔
    user_id mapping.
    """

    def __init__(self, ttl: timedelta = timedelta(minutes=10)) -> None:
        self._ttl = ttl
        self._by_pair_id: dict[str, _Entry] = {}

    def remember(self, *, pair_id: str, user_id: UUID) -> None:
        self._by_pair_id[pair_id] = _Entry(
            user_id=user_id,
            expires_at=datetime.now(timezone.utc) + self._ttl,
        )

    def attach_account(self, *, pair_id: str, account_id: str) -> None:
        e = self._by_pair_id.get(pair_id)
        if e is not None:
            e.account_id = account_id

    def pop_user_for_account(self, *, account_id: str) -> UUID | None:
        # When the bridge posts "paired" it carries account_id but not
        # pair_id; we resolve via the in-flight entries. We keep the entry
        # around (marked completed) so the UI's status poll can still see
        # state="paired" — it'll be cleaned up by `vacuum()` on TTL expiry.
        for _pid, e in list(self._by_pair_id.items()):
            if e.account_id == account_id and not e.completed:
                e.completed = True
                return e.user_id
        return None

    def get_user(self, *, pair_id: str) -> UUID | None:
        e = self._by_pair_id.get(pair_id)
        if e is None:
            return None
        if e.expires_at < datetime.now(timezone.utc):
            self._by_pair_id.pop(pair_id, None)
            return None
        return e.user_id

    def vacuum(self) -> int:
        now = datetime.now(timezone.utc)
        n = 0
        for pid, e in list(self._by_pair_id.items()):
            if e.expires_at < now:
                self._by_pair_id.pop(pid, None)
                n += 1
        return n
