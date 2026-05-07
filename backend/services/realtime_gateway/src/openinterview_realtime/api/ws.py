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
        speaker_verifier=ws.app.state.speaker_verifier,
        max_turn_seconds=settings.realtime_max_turn_seconds,
        transcription_model=settings.realtime_transcription_model,
        noise_reduction=settings.realtime_noise_reduction,
        turn_detection=settings.realtime_turn_detection,
        vad_eagerness=settings.realtime_vad_eagerness,
        speaker_threshold=settings.realtime_speaker_threshold,
        calibration_seconds=settings.realtime_calibration_seconds,
        min_turn_audio_ms=settings.realtime_min_turn_audio_ms,
        min_transcript_confidence=settings.realtime_min_transcript_confidence,
        turn_commit_delay_ms=settings.realtime_turn_commit_delay_ms,
        debug_audio_dir=settings.realtime_debug_audio_dir,
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
