from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from openinterview_logging import get_logger

from ..clients.core_client import CoreClient
from ..clients.gateway_client import GatewayClient
from ..config import Settings
from ..domain.session import LiveSession
from ..domain.ticket import TicketError, verify_ticket

log = get_logger(__name__)
router = APIRouter()


@router.websocket("/ws/interview")
async def ws_interview(ws: WebSocket) -> None:
    await ws.accept()
    settings: Settings = ws.app.state.settings
    gw: GatewayClient = ws.app.state.gateway_client
    core: CoreClient = ws.app.state.core_client

    try:
        hello = await ws.receive_json()
    except WebSocketDisconnect:
        return
    except Exception:
        await _send_error(ws, "expected hello frame")
        await ws.close(code=4400)
        return

    ticket = hello.get("ticket") if isinstance(hello, dict) else None
    if not isinstance(ticket, str):
        await _send_error(ws, "missing ticket")
        await ws.close(code=4401)
        return
    try:
        claims = verify_ticket(ticket, settings.openinterview_realtime_secret)
    except TicketError as e:
        await _send_error(ws, str(e))
        await ws.close(code=4401)
        return

    session = LiveSession(
        ws=ws,
        claims=claims,
        gateway=gw,
        core=core,
        max_turn_seconds=settings.realtime_max_turn_seconds,
    )
    try:
        await session.run()
    except WebSocketDisconnect:
        return
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def _send_error(ws: WebSocket, message: str) -> None:
    try:
        await ws.send_json({"type": "error", "message": message})
    except Exception:
        pass
