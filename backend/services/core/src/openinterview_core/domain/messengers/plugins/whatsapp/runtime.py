"""WhatsApp plugin runtime — backed by a local Node sidecar (Baileys).

Pairing model:
  1. Web UI calls /messaging/pair-tokens — core mints an internal token.
  2. Plugin calls bridge POST /pair, gets pair_id + QR PNG.
  3. UI polls /messaging/pair-tokens/{token}/status — backend forwards
     to bridge GET /pair/{pair_id}/status.
  4. When state = "paired", bridge POSTs `{"type":"paired", account_id,
     phone_number, jid}` to /webhooks/whatsapp/. The plugin matches the
     incoming pair_id to the user who minted the token and writes a
     MessengerLink.

Inbound message model:
  Bridge POSTs `{"type":"message", account_id, jid, phone_number,
  message_id, text, timestamp}` to /webhooks/whatsapp/. Plugin verifies
  HMAC, normalises into InboundTurn, hands to kernel.

Outbound model:
  send_text → POST {bridge_url}/send.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from openinterview_logging import get_logger
from pydantic import BaseModel

from ...sdk.plugin import (
    MessengerCapabilities,
    MessengerIdentity,
    MessengerPlugin,
)
from ...sdk.types import InboundTurn

log = get_logger(__name__)


class PairingHook:
    """Optional callback invoked by the plugin on pair-confirmation
    webhooks so core can attach the freshly-paired account to a user.

    `restored=True` means the bridge brought a previously-paired account
    back online from disk (no QR scan happened); the hook should NOT try
    to mint a link in that case — it already exists from the original
    pairing — but it MAY refresh in-memory caches.
    """

    async def on_paired(
        self,
        *,
        pair_id: str,
        account_id: str,
        jid: str,
        phone_number: str,
        restored: bool = False,
    ) -> None: ...


class WhatsAppPlugin(MessengerPlugin):
    def __init__(
        self,
        *,
        bridge_url: str = "http://127.0.0.1:9300",
        service_token: str = "dev-bridge-token",
        webhook_secret: str | None = "dev-webhook-secret",
        http: httpx.AsyncClient | None = None,
        kernel_handle_turn=None,
        pairing_hook: PairingHook | None = None,
    ) -> None:
        self.identity = MessengerIdentity(
            id="whatsapp",
            name="WhatsApp",
            description=(
                "Pair your personal WhatsApp number using the Linked Devices QR."
            ),
        )
        self.capabilities = MessengerCapabilities(
            streaming=False,
            max_outbound_chars=4000,
            inbound_voice=False,
            inbound_image=False,
            rich_buttons=False,
            ack_window_s=20,
            pair_link_scheme="qr-only",
            supports_typing=False,
        )
        self._bridge = bridge_url.rstrip("/")
        self._token = service_token
        self._secret = webhook_secret
        self._http = http or httpx.AsyncClient(timeout=15.0)
        self._handle_turn = kernel_handle_turn
        self._pairing_hook = pairing_hook

    # ----- pairing API used by /messaging endpoints ------------------------

    async def start_pair(self) -> dict[str, Any]:
        r = await self._http.post(
            f"{self._bridge}/pair", headers=self._auth_headers()
        )
        r.raise_for_status()
        return r.json()

    async def get_pair_status(self, pair_id: str) -> dict[str, Any]:
        r = await self._http.get(
            f"{self._bridge}/pair/{pair_id}/status",
            headers=self._auth_headers(),
        )
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="pair_id not found")
        r.raise_for_status()
        return r.json()

    async def logout_account(self, account_id: str) -> None:
        await self._http.delete(
            f"{self._bridge}/accounts/{account_id}",
            headers=self._auth_headers(),
        )

    async def list_groups(self, account_id: str) -> list[dict[str, Any]]:
        r = await self._http.get(
            f"{self._bridge}/accounts/{account_id}/groups",
            headers=self._auth_headers(),
        )
        r.raise_for_status()
        return list(r.json().get("groups", []))

    async def resolve_invite(
        self, account_id: str, code_or_url: str
    ) -> dict[str, Any]:
        r = await self._http.post(
            f"{self._bridge}/accounts/{account_id}/group-by-invite",
            headers=self._auth_headers(),
            json={"code": code_or_url},
        )
        if r.status_code >= 400:
            raise RuntimeError(r.json().get("error", f"http {r.status_code}"))
        return r.json().get("group", {})

    # ----- inbound (webhook from bridge) ----------------------------------

    def webhook_router(self) -> APIRouter:
        r = APIRouter()

        @r.post("/")
        async def receive(request: Request) -> Response:
            body = await request.body()
            if not await self.verify_signature(request, body):
                raise HTTPException(status_code=401, detail="invalid signature")
            try:
                payload = json.loads(body or b"{}")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="invalid json")
            kind = payload.get("type")
            if kind == "paired":
                # Always refresh the plugin's in-memory routing maps so
                # outbound /send keeps working after a bridge or core
                # restart, regardless of whether this is a fresh pair or
                # a restore.
                acct_id = payload.get("account_id", "")
                jid_in = payload.get("jid", "")
                if acct_id and jid_in:
                    self.remember_account_for_jid(jid=jid_in, account_id=acct_id)
                if self._pairing_hook is not None:
                    try:
                        await self._pairing_hook.on_paired(
                            pair_id=payload.get("pair_id", ""),
                            account_id=acct_id,
                            jid=jid_in,
                            phone_number=payload.get("phone_number", ""),
                            restored=bool(payload.get("restored")),
                        )
                    except Exception as e:  # pragma: no cover
                        log.error("whatsapp_pairing_hook_failed", error=str(e))
                return Response(status_code=200)
            if kind == "message":
                turn = self._payload_to_turn(payload)
                acct = payload.get("account_id")
                # Tie the message back to whichever link/owner this account
                # belongs to so the kernel can resolve filters even when
                # the sender is some other group member.
                if acct:
                    owner_jid = self._owner_jid_for_account.get(acct)
                    if owner_jid:
                        turn.link_external_id = owner_jid
                    if turn.external_user_id and not turn.is_group:
                        self._account_for_jid[turn.external_user_id] = acct
                    if turn.chat_id:
                        self._account_for_chat[turn.chat_id] = acct
                if self._handle_turn is not None:
                    try:
                        await self._handle_turn(self, turn)
                    except Exception as e:
                        log.error(
                            "whatsapp_handle_turn_failed", error=str(e)
                        )
            return Response(status_code=200)

        return r

    async def verify_signature(self, request: Request, body: bytes) -> bool:
        if not self._secret:
            return True
        sig_header = request.headers.get("x-bridge-signature-256", "")
        if not sig_header.startswith("sha256="):
            return False
        expected = hmac.new(
            self._secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header.split("=", 1)[1])

    async def parse_inbound(
        self, request: Request, body: bytes
    ) -> list[InboundTurn]:
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return []
        if payload.get("type") != "message":
            return []
        return [self._payload_to_turn(payload)]

    def _payload_to_turn(self, payload: dict) -> InboundTurn:
        ts = payload.get("timestamp")
        try:
            received_at = (
                datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
                if ts
                else datetime.now(timezone.utc)
            )
        except Exception:
            received_at = datetime.now(timezone.utc)
        sender_jid = payload.get("jid", "")
        chat_jid = payload.get("chat_jid") or sender_jid
        is_group = bool(payload.get("is_group")) or chat_jid.endswith("@g.us")
        return InboundTurn(
            channel="whatsapp",
            external_user_id=sender_jid,
            text=payload.get("text", ""),
            attachments=[],
            message_id=payload.get("message_id"),
            sender_display_name=payload.get("phone_number"),
            received_at=received_at,
            chat_id=chat_jid,
            is_group=is_group,
            raw=payload,
        )

    # ----- outbound -------------------------------------------------------

    async def send_text(
        self,
        to: str,
        text: str,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        # `to` is a wa-jid like "15551234567@s.whatsapp.net". Account is
        # whichever account is currently bound to that jid; the bridge
        # holds that mapping internally.
        # We need an account_id, however: per inbound webhook, the kernel
        # passed external_user_id = jid. To know which account paired with
        # that conversation we look it up via the link; but the link
        # store doesn't track account_id. Resolution: the plugin stores the
        # most recent account_id per jid in memory at inbound time.
        account_id = (
            self._account_for_chat.get(to)
            or self._account_for_jid.get(to)
        )
        if account_id is None:
            log.warning("whatsapp_send_no_account", jid_tail=to[-6:])
            return
        try:
            r = await self._http.post(
                f"{self._bridge}/send",
                headers=self._auth_headers(),
                json={"account_id": account_id, "to_jid": to, "text": text},
            )
            if r.status_code >= 400:
                log.error(
                    "whatsapp_send_failed",
                    status=r.status_code,
                    body=r.text[:512],
                )
        except Exception as e:  # pragma: no cover
            log.error("whatsapp_send_exception", error=str(e))

    async def send_typing(self, to: str) -> None:  # pragma: no cover
        return None

    # ----- helpers --------------------------------------------------------

    _account_for_jid: dict[str, str] = {}
    _account_for_chat: dict[str, str] = {}
    _owner_jid_for_account: dict[str, str] = {}

    def remember_account_for_jid(self, *, jid: str, account_id: str) -> None:
        # `jid` here is the OWNER's jid (set at paired-webhook time). We
        # store both directions so outbound knows the account and inbound
        # can attribute group messages to a link.
        self._account_for_jid[jid] = account_id
        self._owner_jid_for_account[account_id] = jid

    def account_for_link_external_id(self, external_id: str) -> str | None:
        """Resolve `MessengerLink.external_id` (which may be a *previous*
        device-numbered JID like "<phone>:2@s.whatsapp.net") to the
        currently-connected account_id. Falls back to a phone-prefix
        match so re-pairings the same number remain reachable.
        """
        if external_id in self._account_for_jid:
            return self._account_for_jid[external_id]
        local = external_id.split("@", 1)[0]
        phone = local.split(":", 1)[0]
        for owner_jid, acct in self._account_for_jid.items():
            owner_local = owner_jid.split("@", 1)[0]
            if owner_local.split(":", 1)[0] == phone:
                return acct
        return None

    def pair_link_template(self) -> str:
        # We pair via Linked-Devices QR, not via deep link.
        return ""

    async def startup(self) -> None:  # pragma: no cover
        return None

    async def shutdown(self) -> None:
        await self._http.aclose()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


def build_plugin(**config: Any) -> WhatsAppPlugin:
    cfg = {
        "bridge_url": config.get("bridge_url")
        or os.getenv("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:9300"),
        "service_token": config.get("service_token")
        or os.getenv("WHATSAPP_BRIDGE_TOKEN", "dev-bridge-token"),
        "webhook_secret": config.get("webhook_secret")
        or os.getenv("WHATSAPP_BRIDGE_WEBHOOK_SECRET", "dev-webhook-secret"),
    }
    return WhatsAppPlugin(**cfg)


# Optional response model used by /messaging endpoints -- kept here so the
# bridge JSON shape lives next to its only consumer.
class BridgePairOut(BaseModel):
    pair_id: str
    account_id: str
    state: str
    qr_image_b64: str | None = None
    qr_text: str | None = None
    phone_number: str | None = None
    jid: str | None = None
    failure_reason: str | None = None
