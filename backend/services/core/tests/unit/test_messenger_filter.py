"""Unit tests for `apply_filter` — the pure decision function used by the
kernel to drop unwanted inbound turns.
"""
from __future__ import annotations

from openinterview_core.domain.messengers.sdk.filter_store import (
    FilterRule,
    LinkFilter,
    apply_filter,
)


def _flt(mode: str, rules=(), owner="15551112222") -> LinkFilter:
    return LinkFilter(
        mode=mode,
        rules=[FilterRule(id=None, kind=k, value=v, label=None) for k, v in rules],  # type: ignore[arg-type]
        owner_phone=owner,
    )


# ---- dms_only ----------------------------------------------------------------

def test_dms_only_passes_owner_dm_with_device_suffix():
    # Baileys may give us "15551112222:3@s.whatsapp.net" — the ':3' must be ignored.
    assert apply_filter(
        flt=_flt("dms_only"),
        sender_jid="15551112222:3@s.whatsapp.net",
        chat_jid="15551112222:3@s.whatsapp.net",
        is_group=False,
    ) is True


def test_dms_only_drops_groups():
    assert apply_filter(
        flt=_flt("dms_only"),
        sender_jid="15551112222@s.whatsapp.net",
        chat_jid="100-200@g.us",
        is_group=True,
    ) is False


def test_dms_only_drops_other_dm_senders():
    assert apply_filter(
        flt=_flt("dms_only"),
        sender_jid="15559998888@s.whatsapp.net",
        chat_jid="15559998888@s.whatsapp.net",
        is_group=False,
    ) is False


# ---- allowlist ---------------------------------------------------------------

def test_allowlist_phone_match():
    f = _flt("allowlist", rules=(("phone", "15559998888"),))
    assert apply_filter(
        flt=f,
        sender_jid="15559998888@s.whatsapp.net",
        chat_jid="15559998888@s.whatsapp.net",
        is_group=False,
    ) is True


def test_allowlist_group_match():
    f = _flt("allowlist", rules=(("group", "100-200@g.us"),))
    assert apply_filter(
        flt=f,
        sender_jid="15559998888@s.whatsapp.net",
        chat_jid="100-200@g.us",
        is_group=True,
    ) is True


def test_allowlist_no_match_drops():
    f = _flt("allowlist", rules=(("phone", "15559998888"),))
    assert apply_filter(
        flt=f,
        sender_jid="15557776666@s.whatsapp.net",
        chat_jid="15557776666@s.whatsapp.net",
        is_group=False,
    ) is False


# ---- denylist ----------------------------------------------------------------

def test_denylist_blocks_listed_phone_only():
    f = _flt("denylist", rules=(("phone", "15559998888"),))
    assert apply_filter(
        flt=f,
        sender_jid="15559998888@s.whatsapp.net",
        chat_jid="15559998888@s.whatsapp.net",
        is_group=False,
    ) is False
    assert apply_filter(
        flt=f,
        sender_jid="15551234567@s.whatsapp.net",
        chat_jid="15551234567@s.whatsapp.net",
        is_group=False,
    ) is True


# ---- all ---------------------------------------------------------------------

def test_all_lets_everything_through():
    f = _flt("all")
    assert apply_filter(
        flt=f,
        sender_jid="any@s.whatsapp.net",
        chat_jid="100-200@g.us",
        is_group=True,
    ) is True
