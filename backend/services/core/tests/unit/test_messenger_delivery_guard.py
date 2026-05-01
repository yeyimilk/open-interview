"""Tests for DeliveryGuard: repeat-suppression, token-bucket rate limit,
and chunk-paced length splitting.
"""
from __future__ import annotations

import asyncio

import pytest

from openinterview_core.domain.messengers.sdk.delivery_guard import DeliveryGuard
from openinterview_core.domain.messengers.sdk.plugin import MessengerCapabilities


class _FakePlugin:
    plugin_id = "fake"

    def __init__(self, *, max_chars: int = 4000) -> None:
        self.capabilities = MessengerCapabilities(max_outbound_chars=max_chars)
        self.sent: list[tuple[str, str, str | None]] = []

    async def send_text(
        self, *, to: str, text: str, idempotency_key: str | None = None
    ) -> None:
        self.sent.append((to, text, idempotency_key))

    async def on_inbound(self, payload):  # pragma: no cover - not used
        pass

    @property
    def manifest(self):  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_repeat_within_window_is_dropped():
    g = DeliveryGuard(rate_per_second=100, burst=100, recent_window=3, chunk_pause_s=0)
    p = _FakePlugin()

    r1 = await g.deliver(p, to="+1", text="hello")
    r2 = await g.deliver(p, to="+1", text="hello")  # exact repeat
    r3 = await g.deliver(p, to="+1", text="HELLO")  # different (not normalized)

    assert r1.sent_chunks == 1
    assert r2.skipped and r2.reason == "repeat"
    assert r3.sent_chunks == 1
    assert [s[1] for s in p.sent] == ["hello", "HELLO"]


@pytest.mark.asyncio
async def test_repeat_window_only_remembers_last_n():
    g = DeliveryGuard(rate_per_second=100, burst=100, recent_window=3, chunk_pause_s=0)
    p = _FakePlugin()

    for t in ("a", "b", "c", "d"):
        r = await g.deliver(p, to="+1", text=t)
        assert r.sent_chunks == 1

    # "a" fell out of the 3-window — it can be sent again.
    r = await g.deliver(p, to="+1", text="a")
    assert r.sent_chunks == 1


@pytest.mark.asyncio
async def test_repeat_dedup_is_per_recipient():
    g = DeliveryGuard(rate_per_second=100, burst=100, chunk_pause_s=0)
    p = _FakePlugin()
    await g.deliver(p, to="+1", text="hi")
    r = await g.deliver(p, to="+2", text="hi")
    assert r.sent_chunks == 1


@pytest.mark.asyncio
async def test_rate_limit_drops_after_burst():
    g = DeliveryGuard(rate_per_second=0.0001, burst=2, recent_window=10, chunk_pause_s=0)
    p = _FakePlugin()

    r1 = await g.deliver(p, to="+1", text="m1")
    r2 = await g.deliver(p, to="+1", text="m2")
    r3 = await g.deliver(p, to="+1", text="m3")

    assert r1.sent_chunks == 1
    assert r2.sent_chunks == 1
    assert r3.skipped and r3.reason == "rate_limited"


@pytest.mark.asyncio
async def test_long_text_is_chunked_with_pagination_label():
    g = DeliveryGuard(
        rate_per_second=100,
        burst=100,
        recent_window=3,
        chunk_pause_s=0,
        max_chars_per_chunk=50,
    )
    p = _FakePlugin(max_chars=4000)
    long_text = ("Sentence one is here. " * 5) + ("Sentence two is here. " * 5)

    r = await g.deliver(p, to="+1", text=long_text)

    assert r.sent_chunks > 1
    # Every part should be tagged "(i/N) ...".
    for i, (to, text, _) in enumerate(p.sent, start=1):
        assert text.startswith(f"({i}/{r.sent_chunks})")
        assert to == "+1"


@pytest.mark.asyncio
async def test_repeat_suppression_works_after_chunked_delivery():
    g = DeliveryGuard(
        rate_per_second=100,
        burst=100,
        recent_window=3,
        chunk_pause_s=0,
        max_chars_per_chunk=50,
    )
    p = _FakePlugin(max_chars=4000)
    long_text = "A" * 200

    r1 = await g.deliver(p, to="+1", text=long_text)
    r2 = await g.deliver(p, to="+1", text=long_text)

    assert r1.sent_chunks > 1
    assert r2.skipped and r2.reason == "repeat"


@pytest.mark.asyncio
async def test_chunk_pause_actually_sleeps_between_parts(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    g = DeliveryGuard(
        rate_per_second=100,
        burst=100,
        recent_window=3,
        chunk_pause_s=0.25,
        max_chars_per_chunk=20,
    )
    p = _FakePlugin(max_chars=4000)
    await g.deliver(p, to="+1", text="x" * 80)

    # We expect at least one inter-chunk pause of 0.25s.
    assert any(abs(s - 0.25) < 1e-9 for s in sleeps)
