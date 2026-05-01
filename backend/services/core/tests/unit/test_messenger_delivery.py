"""Unit tests for capability-driven outbound chunking."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from openinterview_core.domain.messengers.sdk.delivery import deliver
from openinterview_core.domain.messengers.sdk.plugin import MessengerCapabilities


@dataclass
class _Sent:
    to: str
    text: str
    key: str | None


class _RecordingPlugin:
    def __init__(self, *, max_chars: int = 4000) -> None:
        self.identity = type("I", (), {"id": "fake"})()
        self.capabilities = MessengerCapabilities(max_outbound_chars=max_chars)
        self.sent: list[_Sent] = []

    async def send_text(self, *, to: str, text: str, idempotency_key: str | None = None) -> None:
        self.sent.append(_Sent(to=to, text=text, key=idempotency_key))


@pytest.mark.asyncio
async def test_short_message_sent_once():
    p = _RecordingPlugin()
    r = await deliver(p, to="u1", text="hi")
    assert r.sent_chunks == 1
    assert p.sent[0].text == "hi"


@pytest.mark.asyncio
async def test_empty_message_skipped():
    p = _RecordingPlugin()
    r = await deliver(p, to="u1", text="")
    assert r.sent_chunks == 0
    assert r.skipped is True


@pytest.mark.asyncio
async def test_long_message_chunked_at_paragraph_boundary():
    p = _RecordingPlugin(max_chars=40)
    text = "Paragraph one is here.\n\nParagraph two follows after."
    r = await deliver(p, to="u1", text=text)
    assert r.sent_chunks >= 2
    # First chunk should not exceed the limit
    assert len(p.sent[0].text) <= 40
    # All chunks together should preserve all the source words
    joined = " ".join(s.text for s in p.sent)
    assert "Paragraph one" in joined
    assert "Paragraph two" in joined


@pytest.mark.asyncio
async def test_idempotency_keys_indexed_per_chunk():
    p = _RecordingPlugin(max_chars=20)
    text = "one two three four five six seven eight nine ten"
    await deliver(p, to="u1", text=text, idempotency_key="K")
    keys = [s.key for s in p.sent]
    assert keys[0] == "K:0"
    assert keys[-1] == f"K:{len(p.sent) - 1}"
