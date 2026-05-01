"""WhatsAppPairingTracker — in-memory pair_id ↔ user_id."""
from __future__ import annotations

import uuid
from datetime import timedelta

from openinterview_core.domain.messengers.plugins.whatsapp.pairing import (
    WhatsAppPairingTracker,
)


def test_remember_then_get_user():
    t = WhatsAppPairingTracker()
    uid = uuid.uuid4()
    t.remember(pair_id="P", user_id=uid)
    assert t.get_user(pair_id="P") == uid


def test_attach_account_and_pop_user():
    t = WhatsAppPairingTracker()
    uid = uuid.uuid4()
    t.remember(pair_id="P", user_id=uid)
    t.attach_account(pair_id="P", account_id="A")
    popped = t.pop_user_for_account(account_id="A")
    assert popped == uid
    # Calling again is idempotent — entry stays for the status-poll window
    # but a second pop returns None (already completed).
    assert t.pop_user_for_account(account_id="A") is None
    # The entry is still discoverable by pair_id so the UI can confirm.
    assert t.get_user(pair_id="P") == uid


def test_get_user_returns_none_after_expiry():
    t = WhatsAppPairingTracker(ttl=timedelta(seconds=-1))
    t.remember(pair_id="P", user_id=uuid.uuid4())
    assert t.get_user(pair_id="P") is None


def test_vacuum_removes_expired():
    t = WhatsAppPairingTracker(ttl=timedelta(seconds=-1))
    t.remember(pair_id="P1", user_id=uuid.uuid4())
    t.remember(pair_id="P2", user_id=uuid.uuid4())
    n = t.vacuum()
    assert n == 2


def test_unknown_pair_or_account_returns_none():
    t = WhatsAppPairingTracker()
    assert t.get_user(pair_id="missing") is None
    assert t.pop_user_for_account(account_id="missing") is None
