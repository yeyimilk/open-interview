"""Messaging API: pair sessions, link inventory, plugin list.

Pairing model is plugin-specific. For WhatsApp the plugin asks its bridge
for a fresh QR; for future hypothetical plugins the same /pair-sessions
endpoint may instead return a deep-link template — what comes back is
opaque to the frontend except for `state`, `qr_image_b64`, and the eventual
phone number.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import User

from ...domain.messengers.sdk.filter_store import MessengerFilterStore
from ...domain.messengers.sdk.session_store import MessengerLinkStore
from ...infra.db import get_session_dep
from ..deps import get_current_user

router = APIRouter(prefix="/messaging", tags=["messaging"])


class PluginInfo(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool


class PairSessionOut(BaseModel):
    pair_id: str
    channel: str
    state: str  # waiting | qr | paired | failed
    qr_image_b64: str | None = None
    qr_text: str | None = None
    phone_number: str | None = None
    failure_reason: str | None = None


class LinkOut(BaseModel):
    id: UUID
    channel: str
    external_id: str
    display_name: str | None
    last_seen_at: datetime | None
    created_at: datetime
    filter_mode: str = "dms_only"


class GroupOut(BaseModel):
    jid: str
    subject: str
    participants_count: int


class FilterRuleOut(BaseModel):
    kind: str  # phone | group
    value: str
    label: str | None = None


class FiltersOut(BaseModel):
    mode: str
    rules: list[FilterRuleOut]


class FiltersUpdateRequest(BaseModel):
    mode: str
    rules: list[FilterRuleOut]


class ResolveInviteRequest(BaseModel):
    code: str  # full URL or bare 22-char invite code


class StartPairRequest(BaseModel):
    channel: str


def _whatsapp_runtime(request: Request):
    reg = getattr(request.app.state, "messenger_registry", None)
    tracker = getattr(request.app.state, "whatsapp_pairing_tracker", None)
    if reg is None:
        raise HTTPException(status_code=503, detail="messengers not configured")
    item = reg.get("whatsapp")
    if item is None or tracker is None:
        raise HTTPException(status_code=404, detail="whatsapp plugin not loaded")
    return item[1], tracker


@router.get("/plugins", response_model=list[PluginInfo])
async def list_plugins(request: Request) -> list[PluginInfo]:
    reg = getattr(request.app.state, "messenger_registry", None)
    if reg is None:
        return []
    out: list[PluginInfo] = []
    for manifest, _ in reg.all():
        out.append(
            PluginInfo(
                id=manifest.id,
                name=manifest.name,
                description=manifest.description,
                enabled=True,
            )
        )
    return out


@router.post("/pair-sessions", response_model=PairSessionOut)
async def start_pair_session(
    body: StartPairRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> PairSessionOut:
    if body.channel != "whatsapp":
        raise HTTPException(status_code=400, detail=f"unsupported channel '{body.channel}'")
    plugin, tracker = _whatsapp_runtime(request)
    try:
        s = await plugin.start_pair()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"bridge unavailable: {e}")
    pair_id = s.get("pair_id", "")
    account_id = s.get("account_id")
    tracker.remember(pair_id=pair_id, user_id=user.id)
    if account_id:
        tracker.attach_account(pair_id=pair_id, account_id=account_id)
    return PairSessionOut(
        pair_id=pair_id,
        channel=body.channel,
        state=s.get("state", "waiting"),
        qr_image_b64=s.get("qr_image_b64"),
        qr_text=s.get("qr_text"),
        phone_number=s.get("phone_number"),
        failure_reason=s.get("failure_reason"),
    )


@router.get("/pair-sessions/{pair_id}", response_model=PairSessionOut)
async def get_pair_session(
    pair_id: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> PairSessionOut:
    plugin, tracker = _whatsapp_runtime(request)
    # Tracker enforces "this user owns this pair_id" check.
    owner = tracker.get_user(pair_id=pair_id)
    if owner is None or owner != user.id:
        raise HTTPException(status_code=404, detail="not found")
    try:
        s = await plugin.get_pair_status(pair_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"bridge unavailable: {e}")
    return PairSessionOut(
        pair_id=s.get("pair_id", pair_id),
        channel="whatsapp",
        state=s.get("state", "waiting"),
        qr_image_b64=s.get("qr_image_b64"),
        qr_text=s.get("qr_text"),
        phone_number=s.get("phone_number"),
        failure_reason=s.get("failure_reason"),
    )


@router.get("/links", response_model=list[LinkOut])
async def list_links(
    request: Request,
    user: User = Depends(get_current_user),
) -> list[LinkOut]:
    sm = request.app.state.db.sessionmaker
    rows = await MessengerLinkStore(sm).list_for_user(user_id=user.id)
    return [
        LinkOut(
            id=r.id,
            channel=r.channel,
            external_id=r.external_id,
            display_name=r.display_name,
            last_seen_at=r.last_seen_at,
            created_at=r.created_at,
            filter_mode=getattr(r, "filter_mode", "dms_only") or "dms_only",
        )
        for r in rows
    ]


async def _user_owns_link(sm, user_id, link_id) -> "object | None":
    rows = await MessengerLinkStore(sm).list_for_user(user_id=user_id)
    return next((r for r in rows if r.id == link_id), None)


def _whatsapp_plugin(request: Request):
    reg = getattr(request.app.state, "messenger_registry", None)
    if reg is None:
        raise HTTPException(status_code=503, detail="messengers not configured")
    item = reg.get("whatsapp")
    if item is None:
        raise HTTPException(status_code=404, detail="whatsapp plugin not loaded")
    return item[1]


@router.get("/links/{link_id}/groups", response_model=list[GroupOut])
async def list_link_groups(
    link_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
) -> list[GroupOut]:
    sm = request.app.state.db.sessionmaker
    link = await _user_owns_link(sm, user.id, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="link not found")
    if link.channel != "whatsapp":
        raise HTTPException(status_code=400, detail="only whatsapp supports groups")
    plugin = _whatsapp_plugin(request)
    account_id = plugin.account_for_link_external_id(link.external_id)
    if account_id is None:
        raise HTTPException(
            status_code=503,
            detail="bridge has no live socket for this account; reconnect required",
        )
    try:
        groups = await plugin.list_groups(account_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    return [GroupOut(**g) for g in groups]


@router.post("/links/{link_id}/resolve-invite", response_model=GroupOut)
async def resolve_link_invite(
    link_id: UUID,
    body: ResolveInviteRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> GroupOut:
    sm = request.app.state.db.sessionmaker
    link = await _user_owns_link(sm, user.id, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="link not found")
    if link.channel != "whatsapp":
        raise HTTPException(status_code=400, detail="only whatsapp supports groups")
    plugin = _whatsapp_plugin(request)
    account_id = plugin.account_for_link_external_id(link.external_id)
    if account_id is None:
        raise HTTPException(status_code=503, detail="account not connected")
    try:
        g = await plugin.resolve_invite(account_id, body.code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invite_resolve_failed: {e}")
    return GroupOut(**g)


@router.get("/links/{link_id}/filters", response_model=FiltersOut)
async def get_link_filters(
    link_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
) -> FiltersOut:
    sm = request.app.state.db.sessionmaker
    link = await _user_owns_link(sm, user.id, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="link not found")
    flt = await MessengerFilterStore(sm).load(link_id=link_id)
    if flt is None:
        return FiltersOut(mode="dms_only", rules=[])
    return FiltersOut(
        mode=flt.mode,
        rules=[FilterRuleOut(kind=r.kind, value=r.value, label=r.label) for r in flt.rules],
    )


@router.put("/links/{link_id}/filters", response_model=FiltersOut)
async def put_link_filters(
    link_id: UUID,
    body: FiltersUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> FiltersOut:
    sm = request.app.state.db.sessionmaker
    link = await _user_owns_link(sm, user.id, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="link not found")
    store = MessengerFilterStore(sm)
    try:
        await store.set_mode(link_id=link_id, mode=body.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    rules = [(r.kind, r.value, r.label) for r in body.rules if r.kind in ("phone", "group")]
    saved = await store.replace_rules(link_id=link_id, rules=rules)
    return FiltersOut(
        mode=body.mode,
        rules=[FilterRuleOut(kind=r.kind, value=r.value, label=r.label) for r in saved],
    )


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(
    link_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session_dep),
) -> None:
    sm = request.app.state.db.sessionmaker
    rows = await MessengerLinkStore(sm).list_for_user(user_id=user.id)
    target = next((r for r in rows if r.id == link_id), None)
    ok = await MessengerLinkStore(sm).unlink(user_id=user.id, link_id=link_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not found")

    # Best-effort: if it's a WhatsApp link, also tell the bridge to logout.
    if target is not None and target.channel == "whatsapp":
        reg = request.app.state.messenger_registry
        item = reg.get("whatsapp") if reg else None
        if item is not None:
            plugin = item[1]
            account_id = plugin.account_for_link_external_id(target.external_id)
            if account_id:
                try:
                    await plugin.logout_account(account_id)
                except Exception:
                    pass
                plugin._account_for_jid.pop(target.external_id, None)
    return None
