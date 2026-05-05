"""Per-connection live audio session.

Phase 1 keeps the audio pipeline simple:
  * Client streams audio chunks (binary frames) until it sends
    `{"type": "end_user_turn"}` (or auto-VAD fires).
  * We forward the buffered audio to the gateway's voice analysis endpoint
    to get a transcript + voice features.
  * We POST the transcript to core's internal turn endpoint and SSE-stream
    the assistant tokens back to the client over WS.
  * (TTS streaming added in a later phase.)

Only protocol/orchestration logic lives here; framing helpers live in
`audio/` and HTTP clients in `clients/`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect
from openinterview_logging import get_logger

from ..clients.core_client import CoreCallError, CoreClient
from ..clients.gateway_client import GatewayCallError, GatewayClient
from .ticket import TicketClaims

log = get_logger(__name__)


@dataclass
class LiveSessionState:
    audio_buffer: bytearray = field(default_factory=bytearray)
    audio_mime: str = "audio/webm"
    language: str | None = None
    turn_in_flight: bool = False
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    current_task: asyncio.Task | None = None
    # "idle" | "transcribing" | "responding"
    phase: str = "idle"


class LiveSession:
    def __init__(
        self,
        *,
        ws: WebSocket,
        claims: TicketClaims,
        gateway: GatewayClient,
        core: CoreClient,
        max_turn_seconds: int = 90,
    ) -> None:
        self.ws = ws
        self.claims = claims
        self.gw = gateway
        self.core = core
        self.max_turn_seconds = max_turn_seconds
        self.state = LiveSessionState()

    async def send_json(self, payload: dict) -> None:
        try:
            await self.ws.send_json(payload)
        except Exception:
            pass

    async def run(self) -> None:
        await self.send_json(
            {
                "type": "ready",
                "session_id": str(self.claims.session_id),
            }
        )
        try:
            while True:
                msg = await self.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                # Binary audio frame
                if (b := msg.get("bytes")) is not None:
                    self.state.audio_buffer.extend(b)
                    continue
                text = msg.get("text")
                if text is None:
                    continue
                await self._handle_text_frame(text)
        except WebSocketDisconnect:
            return
        except Exception as e:  # pragma: no cover
            log.error("ws_session_error", error=str(e))
            await self.send_json({"type": "error", "message": str(e)})

    async def _handle_text_frame(self, text: str) -> None:
        import json

        try:
            data = json.loads(text)
        except Exception:
            return
        kind = data.get("type")
        if kind == "config":
            mime = data.get("mime")
            if isinstance(mime, str):
                self.state.audio_mime = mime
            lang = data.get("language")
            if isinstance(lang, str):
                self.state.language = lang
        elif kind == "voice_start":
            # Client VAD detected the user starting to speak. Only abort if
            # the assistant is currently *responding*; if we're still
            # transcribing the previous utterance, let it finish.
            if self.state.phase == "responding":
                self.state.cancel.set()
        elif kind == "end_user_turn":
            await self._handle_turn()
        elif kind == "barge_in":
            self.state.cancel.set()
        elif kind == "mic_pause":
            # Drop the in-flight buffer; client is muting the mic.
            self.state.audio_buffer.clear()
        elif kind == "mic_resume":
            self.state.audio_buffer.clear()
        elif kind == "bye":
            await self.ws.close()

    async def _handle_turn(self) -> None:
        # If the assistant is currently *responding*, cancel it first so the
        # new user input becomes the active turn (ChatGPT-style barge-in).
        # Don't cancel a transcription that's already running for the
        # previous utterance — let it finish so the prior turn produces a
        # reply that becomes part of chat history.
        if self.state.turn_in_flight and self.state.phase == "responding":
            self.state.cancel.set()
            prev = self.state.current_task
            if prev is not None:
                try:
                    await asyncio.wait_for(prev, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass
        if not self.state.audio_buffer:
            return
        audio = bytes(self.state.audio_buffer)
        self.state.audio_buffer.clear()
        self.state.cancel.clear()
        self.state.turn_in_flight = True

        async def _runner() -> None:
            try:
                await self._run_turn(audio)
            finally:
                self.state.turn_in_flight = False
                self.state.phase = "idle"

        self.state.current_task = asyncio.create_task(_runner())

    async def _run_turn(self, audio: bytes) -> None:
        # 1) STT + voice features (cancel-only-on-explicit-barge_in)
        self.state.phase = "transcribing"
        try:
            v = await self.gw.analyze_voice(
                user_id=str(self.claims.user_id),
                audio=audio,
                mime=self.state.audio_mime,
                language=self.state.language,
            )
        except GatewayCallError as e:
            log.warning("analyze_voice_failed", error=str(e))
            self.state.phase = "idle"
            return
        analysis = v.get("analysis") or {}
        transcript = (analysis.get("transcript") or "").strip()
        if not transcript:
            # Silent / no speech: stay quiet rather than yelling errors. The
            # client may have committed on a borderline buffer.
            self.state.phase = "idle"
            return
        await self.send_json(
            {
                "type": "final_transcript",
                "text": transcript,
                "voice": analysis,
            }
        )

        # 2) Run agent via core (persists user + assistant messages there)
        self.state.phase = "responding"
        self.state.cancel.clear()
        full_chunks: list[str] = []
        try:
            async for ev in self.core.stream_interviewer_turn(
                user_id=str(self.claims.user_id),
                session_id=str(self.claims.session_id),
                transcript=transcript,
                voice=analysis,
            ):
                if self.state.cancel.is_set():
                    break
                payload = ev.get("data") or {}
                kind = payload.get("type") or ev.get("event")
                if kind == "token":
                    piece = payload.get("content", "")
                    if piece:
                        full_chunks.append(piece)
                        await self.send_json(
                            {"type": "assistant_token", "text": piece}
                        )
                elif kind == "done":
                    await self.send_json({"type": "assistant_done"})
                    self.state.phase = "idle"
                    return
                elif kind == "error":
                    await self.send_json(
                        {
                            "type": "error",
                            "message": str(payload.get("message", "stream error")),
                        }
                    )
                    self.state.phase = "idle"
                    return
        except CoreCallError as e:
            log.warning("core_stream_failed", error=str(e))
            self.state.phase = "idle"
            return
        # Loop ended without a `done` event — treat as completion.
        await self.send_json({"type": "assistant_done"})
        self.state.phase = "idle"
