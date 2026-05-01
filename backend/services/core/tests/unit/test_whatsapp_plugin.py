"""Unit tests for the WhatsApp plugin runtime (Baileys bridge backend)."""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from openinterview_core.domain.messengers.plugins.whatsapp.runtime import (
    WhatsAppPlugin,
    build_plugin,
)


def _mk(**overrides) -> WhatsAppPlugin:
    handler = overrides.pop("handler", None)
    transport = httpx.MockTransport(handler) if handler else None
    client = httpx.AsyncClient(transport=transport) if transport else None
    return WhatsAppPlugin(
        bridge_url=overrides.get("bridge_url", "http://bridge:9300"),
        service_token=overrides.get("service_token", "tok"),
        webhook_secret=overrides.get("webhook_secret", "secret"),
        http=client,
    )


def test_capabilities_advertise_qr_only_pairing():
    p = _mk()
    assert p.capabilities.pair_link_scheme == "qr-only"
    assert p.capabilities.streaming is False
    # pair_link_template is empty for qr-only channels.
    assert p.pair_link_template() == ""


@pytest.mark.asyncio
async def test_signature_disabled_when_no_secret_accepts_everything():
    p = _mk(webhook_secret=None)

    class _Req:
        headers: dict[str, str] = {}

    assert await p.verify_signature(_Req(), b"") is True


@pytest.mark.asyncio
async def test_signature_verify_accepts_correct_hmac():
    p = _mk()
    body = b'{"x":1}'
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    class _Req:
        headers = {"x-bridge-signature-256": f"sha256={digest}"}

    assert await p.verify_signature(_Req(), body) is True


@pytest.mark.asyncio
async def test_signature_verify_rejects_wrong_or_missing():
    p = _mk()

    class _BadReq:
        headers = {"x-bridge-signature-256": "sha256=deadbeef"}

    assert await p.verify_signature(_BadReq(), b'{"x":1}') is False

    class _MissingReq:
        headers: dict[str, str] = {}

    assert await p.verify_signature(_MissingReq(), b'{"x":1}') is False


@pytest.mark.asyncio
async def test_parse_inbound_message_payload():
    p = _mk()
    body = json.dumps(
        {
            "type": "message",
            "account_id": "acc-1",
            "jid": "15551112222@s.whatsapp.net",
            "phone_number": "15551112222",
            "message_id": "WAID-1",
            "text": "/mentor",
            "timestamp": 1700000000000,
        }
    ).encode()
    turns = await p.parse_inbound(None, body)
    assert len(turns) == 1
    t = turns[0]
    assert t.channel == "whatsapp"
    assert t.external_user_id == "15551112222@s.whatsapp.net"
    assert t.text == "/mentor"
    assert t.message_id == "WAID-1"
    assert t.sender_display_name == "15551112222"


@pytest.mark.asyncio
async def test_parse_inbound_skips_non_message_payloads():
    p = _mk()
    body = json.dumps({"type": "paired", "account_id": "x"}).encode()
    assert await p.parse_inbound(None, body) == []
    assert await p.parse_inbound(None, b"") == []
    assert await p.parse_inbound(None, b"not-json") == []


@pytest.mark.asyncio
async def test_start_pair_calls_bridge():
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(
            200,
            json={
                "pair_id": "P-1",
                "account_id": "A-1",
                "state": "qr",
                "qr_image_b64": "data:image/png;base64,XXX",
                "qr_text": "raw-qr",
                "phone_number": None,
                "jid": None,
                "failure_reason": None,
            },
        )

    p = _mk(handler=handler)
    out = await p.start_pair()
    assert out["pair_id"] == "P-1"
    assert out["qr_image_b64"].startswith("data:image/png;base64,")
    assert captured[0].method == "POST"
    assert str(captured[0].url) == "http://bridge:9300/pair"
    assert captured[0].headers["authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_get_pair_status_404_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found"})

    p = _mk(handler=handler)
    with pytest.raises(Exception):
        await p.get_pair_status("missing")


@pytest.mark.asyncio
async def test_send_text_routes_to_bridge_with_account():
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"ok": True})

    p = _mk(handler=handler)
    p.remember_account_for_jid(jid="1@s.whatsapp.net", account_id="A-1")
    await p.send_text(to="1@s.whatsapp.net", text="hello")

    assert len(captured) == 1
    body = json.loads(captured[0].content)
    assert body == {
        "account_id": "A-1",
        "to_jid": "1@s.whatsapp.net",
        "text": "hello",
    }


@pytest.mark.asyncio
async def test_send_text_without_known_account_silently_drops():
    # If we don't know the bridge account for this jid, we should NOT crash.
    posts: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        posts.append(req)
        return httpx.Response(200, json={"ok": True})

    p = _mk(handler=handler)
    await p.send_text(to="unknown@s.whatsapp.net", text="hi")
    assert posts == []


def test_build_plugin_reads_env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_BRIDGE_URL", "http://bridge.test")
    monkeypatch.setenv("WHATSAPP_BRIDGE_TOKEN", "T")
    monkeypatch.setenv("WHATSAPP_BRIDGE_WEBHOOK_SECRET", "S")
    p = build_plugin()
    assert p._bridge == "http://bridge.test"
    assert p._token == "T"
    assert p._secret == "S"
