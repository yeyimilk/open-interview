"""Per-connection live audio session.

The browser streams 24 kHz mono PCM to this gateway. The gateway owns the
OpenAI Realtime transcription socket, keeps raw provider keys in the GenAI
gateway, and only forwards accepted primary-speaker transcripts to core.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import WebSocket, WebSocketDisconnect
from openinterview_logging import get_logger

from ..audio import (
    AudioDebugContext,
    AudioDebugDumper,
    SpeakerProfile,
    SpeakerVerificationError,
    SpeakerVerifier,
)
from ..clients.core_client import CoreCallError, CoreClient
from ..clients.gateway_client import GatewayClient
from ..clients.openai_realtime import OpenAIRealtimeTranscriber
from .ticket import TicketClaims
from .turn_buffer import PendingTurnBuffer

log = get_logger(__name__)


class RealtimeTranscriber(Protocol):
    async def connect(self) -> None: ...

    async def send_audio(self, pcm16: bytes) -> None: ...

    async def clear_audio(self) -> None: ...

    def events(self) -> AsyncIterator[dict]: ...

    async def close(self) -> None: ...


TranscriberFactory = Callable[[dict], Awaitable[RealtimeTranscriber]]


@dataclass
class LiveSessionState:
    language: str | None = None
    audio_format: str = "pcm16"
    sample_rate: int = 24000
    channels: int = 1
    turn_in_flight: bool = False
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    current_task: asyncio.Task | None = None
    realtime_task: asyncio.Task | None = None
    transcriber: RealtimeTranscriber | None = None
    speaker_profile: SpeakerProfile | None = None
    calibrating: bool = False
    mic_paused: bool = False
    calibration_buffer: bytearray = field(default_factory=bytearray)
    prebuffer: bytearray = field(default_factory=bytearray)
    collecting_turn: bool = False
    active_turn_audio: bytearray = field(default_factory=bytearray)
    last_turn_audio: bytes = b""
    turn_audio_by_item: dict[str, bytes] = field(default_factory=dict)
    outstanding_item_ids: set[str] = field(default_factory=set)
    completed_item_ids: set[str] = field(default_factory=set)
    seen_audio_transcript_keys: set[str] = field(default_factory=set)
    pending_turn: PendingTurnBuffer = field(default_factory=PendingTurnBuffer)
    pending_turn_task: asyncio.Task | None = None
    speech_started_at: float | None = None
    last_speech_stopped_at: float | None = None
    # "idle" | "responding"
    phase: str = "idle"


class LiveSession:
    def __init__(
        self,
        *,
        ws: WebSocket,
        claims: TicketClaims,
        gateway: GatewayClient,
        core: CoreClient,
        speaker_verifier: SpeakerVerifier,
        max_turn_seconds: int = 90,
        transcription_model: str = "gpt-4o-transcribe",
        noise_reduction: str | None = "near_field",
        turn_detection: str = "semantic_vad",
        vad_eagerness: str = "low",
        speaker_threshold: float = 0.25,
        calibration_seconds: float = 5.0,
        min_turn_audio_ms: int = 300,
        min_transcript_confidence: float = 0.35,
        turn_commit_delay_ms: int = 1200,
        debug_audio_dir: str = "",
        transcriber_factory: TranscriberFactory | None = None,
    ) -> None:
        self.ws = ws
        self.claims = claims
        self.gw = gateway
        self.core = core
        self.speaker_verifier = speaker_verifier
        self.max_turn_seconds = max_turn_seconds
        self.transcription_model = transcription_model
        self.noise_reduction = noise_reduction
        self.turn_detection = turn_detection
        self.vad_eagerness = vad_eagerness
        self.speaker_threshold = speaker_threshold
        self.calibration_seconds = calibration_seconds
        self.min_turn_audio_ms = min_turn_audio_ms
        self.min_transcript_confidence = min_transcript_confidence
        self.turn_commit_delay_ms = turn_commit_delay_ms
        self.audio_debug = AudioDebugDumper(debug_audio_dir)
        self._transcriber_factory = transcriber_factory
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
        await self._send_calibration_required()
        try:
            while True:
                msg = await self.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                if (b := msg.get("bytes")) is not None:
                    await self._handle_audio(b)
                    continue
                text = msg.get("text")
                if text is not None:
                    await self._handle_text_frame(text)
        except WebSocketDisconnect:
            return
        except Exception as e:  # pragma: no cover
            log.error("ws_session_error", error=str(e))
            await self.send_json({"type": "error", "message": str(e)})
        finally:
            await self.close()

    async def close(self) -> None:
        for task in (
            self.state.realtime_task,
            self.state.current_task,
            self.state.pending_turn_task,
        ):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
        if self.state.transcriber is not None:
            with suppress(Exception):
                await self.state.transcriber.close()
        self.state.transcriber = None

    async def _send_calibration_required(self) -> None:
        await self.send_json(
            {
                "type": "calibration_required",
                "duration_ms": int(self.calibration_seconds * 1000),
                "sample_rate": self.state.sample_rate,
            }
        )

    async def _handle_audio(self, audio: bytes) -> None:
        if not audio:
            return
        if self.state.calibrating:
            self.state.calibration_buffer.extend(audio)
            return
        if self.state.mic_paused or self.state.speaker_profile is None:
            return
        self._append_prebuffer(audio)
        if self.state.collecting_turn:
            self.state.active_turn_audio.extend(audio)
            self._trim_active_turn_audio()
        if self.state.transcriber is None:
            await self._ensure_transcriber()
        if self.state.transcriber is not None:
            await self.state.transcriber.send_audio(audio)

    async def _handle_text_frame(self, text: str) -> None:
        import json

        try:
            data = json.loads(text)
        except Exception:
            return
        kind = data.get("type")
        if kind == "config":
            self._apply_config(data)
        elif kind == "calibration_start":
            self.state.calibrating = True
            self.state.calibration_buffer.clear()
        elif kind == "calibration_commit":
            await self._finish_calibration()
        elif kind == "barge_in":
            self.state.cancel.set()
        elif kind == "mic_pause":
            self.state.mic_paused = True
            self._clear_turn_audio()
            if self.state.transcriber is not None:
                with suppress(Exception):
                    await self.state.transcriber.clear_audio()
        elif kind == "mic_resume":
            self.state.mic_paused = False
            self._clear_turn_audio()
        elif kind == "bye":
            await self.ws.close()

    def _apply_config(self, data: dict) -> None:
        fmt = data.get("audio_format")
        if isinstance(fmt, str):
            self.state.audio_format = fmt
        sr = data.get("sample_rate")
        if isinstance(sr, int):
            self.state.sample_rate = sr
        channels = data.get("channels")
        if isinstance(channels, int):
            self.state.channels = channels
        lang = data.get("language")
        if isinstance(lang, str):
            self.state.language = lang

    async def _finish_calibration(self) -> None:
        audio = bytes(self.state.calibration_buffer)
        self.state.calibration_buffer.clear()
        self.state.calibrating = False
        calibration_dump = self._dump_debug_audio(
            label="calibration",
            audio=audio,
            metadata={
                "kind": "calibration",
                "duration_s": self._audio_duration_s(audio),
            },
        )
        try:
            profile = await self.speaker_verifier.enroll(
                pcm16=audio,
                sample_rate=self.state.sample_rate,
            )
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            retryable = _is_retryable_calibration_error(msg)
            log.warning(
                "speaker_calibration_failed",
                error=msg,
                retryable=retryable,
                audio_path=calibration_dump,
                duration_s=self._audio_duration_s(audio),
            )
            await self._send_calibration_error(msg, retryable=retryable)
            if retryable:
                await self._send_calibration_required()
            return
        self.state.speaker_profile = profile
        log.info(
            "speaker_calibration_ready",
            profile_quality=profile.quality,
            profile_duration_s=profile.duration_s,
            speaker_threshold=self.speaker_threshold,
            audio_path=calibration_dump,
        )
        try:
            await self._ensure_transcriber()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            log.warning("realtime_transcriber_start_failed", error=msg)
            self.state.speaker_profile = None
            await self._send_calibration_error(msg, retryable=False)
            return
        await self.send_json({"type": "calibration_ready"})
        await self.send_json(
            {
                "type": "ready",
                "session_id": str(self.claims.session_id),
            }
        )

    async def _ensure_transcriber(self) -> None:
        if self.state.transcriber is not None:
            return
        if self._transcriber_factory is not None:
            transcriber = await self._transcriber_factory({})
        else:
            session = await self.gw.create_realtime_transcription_session(
                user_id=str(self.claims.user_id),
                model=self.transcription_model,
                language=self.state.language,
                noise_reduction=self.noise_reduction,
                turn_detection=self.turn_detection,
                vad_eagerness=self.vad_eagerness,
                include_logprobs=True,
            )
            transcriber = OpenAIRealtimeTranscriber(
                ws_url=str(session["ws_url"]),
                client_secret=str(session["client_secret"]),
            )
            await transcriber.connect()
        self.state.transcriber = transcriber
        self.state.realtime_task = asyncio.create_task(self._consume_realtime())

    async def _consume_realtime(self) -> None:
        transcriber = self.state.transcriber
        if transcriber is None:
            return
        try:
            async for event in transcriber.events():
                await self._handle_realtime_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("realtime_transcription_stream_failed", error=str(e))
            await self.send_json({"type": "error", "message": "realtime transcription failed"})

    async def _handle_realtime_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "input_audio_buffer.speech_started":
            now = asyncio.get_running_loop().time()
            gap_s = (
                None
                if self.state.last_speech_stopped_at is None
                else now - self.state.last_speech_stopped_at
            )
            pending_parts = self.state.pending_turn.part_count
            if pending_parts:
                log.info(
                    "live_turn_merge_window_extended",
                    gap_s=gap_s,
                    pending_parts=pending_parts,
                    pending_item_ids=self.state.pending_turn.item_ids,
                )
            self._cancel_pending_turn_commit()
            self.state.speech_started_at = now
            self.state.collecting_turn = True
            self.state.active_turn_audio = bytearray(self.state.prebuffer)
            log.info(
                "live_speech_started",
                gap_s=gap_s,
                prebuffer_duration_s=self._audio_duration_s(self.state.prebuffer),
            )
            await self.send_json({"type": "user_speech_started"})
        elif kind == "input_audio_buffer.speech_stopped":
            now = asyncio.get_running_loop().time()
            self.state.collecting_turn = False
            self.state.last_turn_audio = bytes(self.state.active_turn_audio)
            self.state.active_turn_audio.clear()
            speech_duration_s = (
                None
                if self.state.speech_started_at is None
                else now - self.state.speech_started_at
            )
            self.state.last_speech_stopped_at = now
            log.info(
                "live_speech_stopped",
                speech_duration_s=speech_duration_s,
                audio_duration_s=self._audio_duration_s(self.state.last_turn_audio),
                audio_bytes=len(self.state.last_turn_audio),
            )
            await self._maybe_schedule_pending_turn_commit(reason="speech_stopped")
        elif kind == "input_audio_buffer.committed":
            item_id = str(event.get("item_id") or "")
            audio = self.state.last_turn_audio or bytes(self.state.active_turn_audio)
            if item_id:
                self._cancel_pending_turn_commit()
                self.state.outstanding_item_ids.add(item_id)
                if audio:
                    self.state.turn_audio_by_item[item_id] = audio
                log.info(
                    "live_audio_committed",
                    item_id=item_id,
                    audio_duration_s=self._audio_duration_s(audio),
                    audio_bytes=len(audio),
                )
        elif kind == "conversation.item.input_audio_transcription.completed":
            item_id = str(event.get("item_id") or "")
            if item_id:
                self.state.outstanding_item_ids.discard(item_id)
            if item_id and item_id in self.state.completed_item_ids:
                log.info("live_transcript_duplicate_item_ignored", item_id=item_id)
                await self._maybe_schedule_pending_turn_commit(
                    reason="duplicate_item_ignored"
                )
                return
            audio = (
                self.state.turn_audio_by_item.pop(item_id, b"")
                or self.state.last_turn_audio
                or bytes(self.state.active_turn_audio)
            )
            transcript = str(event.get("transcript") or "")
            key = _audio_transcript_key(transcript=transcript, audio=audio)
            if key in self.state.seen_audio_transcript_keys:
                log.info(
                    "live_transcript_duplicate_audio_ignored",
                    item_id=item_id or None,
                    transcript_chars=len(transcript.strip()),
                    audio_duration_s=self._audio_duration_s(audio),
                )
                if item_id:
                    self.state.completed_item_ids.add(item_id)
                await self._maybe_schedule_pending_turn_commit(
                    reason="duplicate_audio_ignored"
                )
                return
            self.state.seen_audio_transcript_keys.add(key)
            if item_id:
                self.state.completed_item_ids.add(item_id)
            await self._handle_completed_transcript(
                transcript=transcript,
                audio=audio,
                logprobs=event.get("logprobs"),
                item_id=item_id or None,
            )
        elif kind == "conversation.item.input_audio_transcription.failed":
            item_id = str(event.get("item_id") or "")
            if item_id:
                self.state.outstanding_item_ids.discard(item_id)
            log.info("realtime_transcription_failed", item_id=item_id or None)
            if self.state.pending_turn.has_parts:
                await self._maybe_schedule_pending_turn_commit(
                    reason="transcription_failed_with_pending"
                )
            else:
                await self._send_turn_ignored(reason="transcription_failed")

    async def _handle_completed_transcript(
        self,
        *,
        transcript: str,
        audio: bytes,
        logprobs: object = None,
        item_id: str | None = None,
    ) -> None:
        transcript = (transcript or "").strip()
        if not transcript:
            await self._send_turn_ignored(reason="empty_transcript")
            return
        fragment_dump = self._dump_debug_audio(
            label=f"fragment_{item_id or 'no_item'}",
            audio=audio,
            transcript=transcript,
            metadata={
                "kind": "fragment",
                "item_id": item_id,
                "duration_s": self._audio_duration_s(audio),
                "transcript_chars": len(transcript),
            },
        )
        log.info(
            "live_transcript_fragment",
            item_id=item_id,
            transcript_chars=len(transcript),
            audio_duration_s=self._audio_duration_s(audio),
            audio_bytes=len(audio),
            audio_path=fragment_dump,
        )
        self.state.pending_turn.add(
            transcript=transcript,
            audio=audio,
            item_id=item_id,
            logprobs=logprobs,
        )
        await self._maybe_schedule_pending_turn_commit(reason="transcript_completed")

    async def _maybe_schedule_pending_turn_commit(self, *, reason: str) -> None:
        if not self.state.pending_turn.has_parts:
            return
        if self.state.collecting_turn or self.state.outstanding_item_ids:
            log.info(
                "live_turn_commit_deferred",
                reason=reason,
                collecting_turn=self.state.collecting_turn,
                outstanding_item_ids=sorted(self.state.outstanding_item_ids),
                pending_parts=self.state.pending_turn.part_count,
                pending_item_ids=self.state.pending_turn.item_ids,
            )
            return
        await self._schedule_pending_turn_commit(reason=reason)

    async def _schedule_pending_turn_commit(self, *, reason: str) -> None:
        self._cancel_pending_turn_commit()
        delay_s = max(0, self.turn_commit_delay_ms) / 1000
        if delay_s <= 0:
            await self.send_json({"type": "user_speech_stopped"})
            await self._commit_pending_turn()
            return
        await self.send_json({"type": "user_speech_stopped"})
        log.info(
            "live_turn_commit_scheduled",
            reason=reason,
            delay_s=delay_s,
            pending_parts=self.state.pending_turn.part_count,
            pending_item_ids=self.state.pending_turn.item_ids,
        )

        async def _runner() -> None:
            try:
                await asyncio.sleep(delay_s)
                await self._commit_pending_turn()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("pending_live_turn_commit_failed", error=str(e))

        self.state.pending_turn_task = asyncio.create_task(_runner())

    async def _commit_pending_turn(self) -> None:
        self.state.pending_turn_task = None
        candidate = self.state.pending_turn.pop_candidate()
        turn_sequence = candidate.sequence
        transcript = candidate.transcript
        audio = candidate.audio
        merged_dump = self._dump_debug_audio(
            label=f"turn_{turn_sequence:04d}_merged",
            audio=audio,
            transcript=transcript,
            metadata={
                "kind": "merged_turn",
                "turn_sequence": turn_sequence,
                "item_ids": candidate.item_ids,
                "part_count": candidate.part_count,
                "duration_s": self._audio_duration_s(audio),
                "transcript_chars": len(transcript),
            },
        )
        log.info(
            "live_turn_commit_candidate",
            turn_sequence=turn_sequence,
            item_ids=candidate.item_ids,
            part_count=candidate.part_count,
            transcript_chars=len(transcript),
            audio_duration_s=self._audio_duration_s(audio),
            audio_bytes=len(audio),
            audio_path=merged_dump,
        )
        if not transcript:
            await self._send_turn_ignored(reason="empty_transcript")
            return
        if self.state.speaker_profile is None:
            log.info(
                "live_turn_rejected",
                reason="missing_speaker_profile",
                turn_sequence=turn_sequence,
                audio_path=merged_dump,
            )
            await self._send_turn_ignored(reason="missing_speaker_profile")
            return
        min_bytes = int(self.state.sample_rate * 2 * self.min_turn_audio_ms / 1000)
        if len(audio) < min_bytes:
            log.info(
                "live_turn_rejected",
                reason="too_short",
                turn_sequence=turn_sequence,
                audio_path=merged_dump,
            )
            await self._send_turn_ignored(reason="too_short")
            return
        try:
            speaker_score = await self.speaker_verifier.score(
                profile=self.state.speaker_profile,
                pcm16=audio,
                sample_rate=self.state.sample_rate,
            )
        except (SpeakerVerificationError, Exception) as e:  # noqa: BLE001
            log.warning(
                "live_turn_rejected",
                reason="speaker_verifier_error",
                error=str(e),
                turn_sequence=turn_sequence,
                audio_path=merged_dump,
            )
            await self._send_turn_ignored(reason="speaker_verifier_error")
            return
        if speaker_score < self.speaker_threshold:
            log.info(
                "live_turn_rejected",
                reason="speaker_mismatch",
                turn_sequence=turn_sequence,
                speaker_score=speaker_score,
                threshold=self.speaker_threshold,
                audio_path=merged_dump,
            )
            await self._send_turn_ignored(reason="speaker_mismatch")
            return
        confidence = _confidence_from_logprobs(candidate.logprobs)
        if (
            confidence is not None
            and confidence < self.min_transcript_confidence
        ):
            log.info(
                "live_turn_rejected",
                reason="low_transcript_confidence",
                turn_sequence=turn_sequence,
                confidence=confidence,
                threshold=self.min_transcript_confidence,
                audio_path=merged_dump,
            )
            await self._send_turn_ignored(reason="low_transcript_confidence")
            return

        duration_s = len(audio) / max(1, self.state.sample_rate * 2)
        voice = {
            "transcript": transcript,
            "duration_s": duration_s,
            "speaker_score": speaker_score,
            "speaker_profile_quality": self.state.speaker_profile.quality,
            "transcript_confidence": confidence,
            "preprocessing": {
                "noise_reduction": self.noise_reduction,
                "turn_detection": self.turn_detection,
                "speaker_threshold": self.speaker_threshold,
            },
            "channel": "live",
        }
        await self._start_core_turn(transcript=transcript, voice=voice)
        log.info(
            "live_turn_accepted",
            turn_sequence=turn_sequence,
            speaker_score=speaker_score,
            threshold=self.speaker_threshold,
            confidence=confidence,
            audio_path=merged_dump,
        )

    async def _start_core_turn(self, *, transcript: str, voice: dict) -> None:
        if self.state.turn_in_flight and self.state.phase == "responding":
            self.state.cancel.set()
            prev = self.state.current_task
            if prev is not None:
                with suppress(asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    await asyncio.wait_for(prev, timeout=2.0)
        self.state.cancel.clear()
        self.state.turn_in_flight = True
        await self.send_json(
            {
                "type": "final_transcript",
                "text": transcript,
                "voice": voice,
            }
        )

        async def _runner() -> None:
            try:
                await self._run_core_turn(transcript=transcript, voice=voice)
            finally:
                self.state.turn_in_flight = False
                self.state.phase = "idle"

        self.state.current_task = asyncio.create_task(_runner())

    async def _send_calibration_error(
        self, message: str, *, retryable: bool
    ) -> None:
        await self.send_json(
            {
                "type": "calibration_error",
                "message": message,
                "retryable": retryable,
            }
        )

    async def _send_turn_ignored(self, *, reason: str) -> None:
        await self.send_json({"type": "turn_ignored", "reason": reason})

    async def _run_core_turn(self, *, transcript: str, voice: dict) -> None:
        self.state.phase = "responding"
        try:
            async for ev in self.core.stream_interviewer_turn(
                user_id=str(self.claims.user_id),
                session_id=str(self.claims.session_id),
                transcript=transcript,
                voice=voice,
            ):
                if self.state.cancel.is_set():
                    break
                payload = ev.get("data") or {}
                kind = payload.get("type") or ev.get("event")
                if kind == "token":
                    piece = payload.get("content", "")
                    if piece:
                        await self.send_json(
                            {"type": "assistant_token", "text": piece}
                        )
                elif kind == "done":
                    await self.send_json({"type": "assistant_done"})
                    return
                elif kind == "error":
                    await self.send_json(
                        {
                            "type": "error",
                            "message": str(payload.get("message", "stream error")),
                        }
                    )
                    return
        except CoreCallError as e:
            log.warning("core_stream_failed", error=str(e))
            await self.send_json(
                {"type": "error", "message": "interviewer stream failed"}
            )
            return
        await self.send_json({"type": "assistant_done"})

    def _append_prebuffer(self, audio: bytes) -> None:
        self.state.prebuffer.extend(audio)
        max_bytes = self.state.sample_rate * 2 * 3
        if len(self.state.prebuffer) > max_bytes:
            del self.state.prebuffer[: len(self.state.prebuffer) - max_bytes]

    def _trim_active_turn_audio(self) -> None:
        max_bytes = max(1, self.state.sample_rate * 2 * self.max_turn_seconds)
        if len(self.state.active_turn_audio) > max_bytes:
            overflow = len(self.state.active_turn_audio) - max_bytes
            del self.state.active_turn_audio[:overflow]

    def _audio_duration_s(self, audio: bytes | bytearray) -> float:
        return self.audio_debug.duration_s(
            audio,
            sample_rate=self.state.sample_rate,
            channels=self.state.channels,
        )

    def _dump_debug_audio(
        self,
        *,
        label: str,
        audio: bytes | bytearray,
        transcript: str | None = None,
        metadata: dict | None = None,
    ) -> str | None:
        return self.audio_debug.dump(
            context=AudioDebugContext(
                session_id=str(self.claims.session_id),
                user_id=str(self.claims.user_id),
                sample_rate=self.state.sample_rate,
                channels=self.state.channels,
                audio_format=self.state.audio_format,
            ),
            label=label,
            audio=audio,
            transcript=transcript,
            metadata=metadata,
        )

    def _cancel_pending_turn_commit(self) -> None:
        task = self.state.pending_turn_task
        if (
            task is not None
            and task is not asyncio.current_task()
            and not task.done()
        ):
            task.cancel()
        self.state.pending_turn_task = None

    def _clear_turn_audio(self) -> None:
        self._cancel_pending_turn_commit()
        self.state.prebuffer.clear()
        self.state.active_turn_audio.clear()
        self.state.last_turn_audio = b""
        self.state.turn_audio_by_item.clear()
        self.state.outstanding_item_ids.clear()
        self.state.completed_item_ids.clear()
        self.state.seen_audio_transcript_keys.clear()
        self.state.pending_turn.clear()
        self.state.speech_started_at = None
        self.state.last_speech_stopped_at = None
        self.state.collecting_turn = False


def _confidence_from_logprobs(logprobs: object) -> float | None:
    if not isinstance(logprobs, list):
        return None
    vals: list[float] = []
    for row in logprobs:
        if not isinstance(row, dict):
            continue
        value = row.get("logprob")
        if isinstance(value, (int, float)):
            vals.append(math.exp(float(value)))
    if not vals:
        return None
    return sum(vals) / len(vals)


def _audio_transcript_key(*, transcript: str, audio: bytes) -> str:
    sample = audio[:4096] + audio[-4096:] if len(audio) > 8192 else audio
    digest = hashlib.sha1(sample).hexdigest()
    normalized_text = " ".join((transcript or "").strip().lower().split())
    return f"{normalized_text}\0{len(audio)}\0{digest}"


def _is_retryable_calibration_error(message: str) -> bool:
    low = (message or "").lower()
    if "install openinterview-realtime[speaker]" in low:
        return False
    if "required for speaker verification" in low:
        return False
    return True
