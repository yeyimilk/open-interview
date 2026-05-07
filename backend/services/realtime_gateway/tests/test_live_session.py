from __future__ import annotations

import time
import uuid

import pytest

from openinterview_realtime.audio import SpeakerProfile
from openinterview_realtime.clients.core_client import CoreCallError
from openinterview_realtime.domain.session import LiveSession
from openinterview_realtime.domain.ticket import TicketClaims


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        pass


class FakeCore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def stream_interviewer_turn(self, **kwargs):
        self.calls.append(kwargs)
        yield {"event": "token", "data": {"type": "token", "content": "ok"}}
        yield {"event": "done", "data": {"type": "done"}}


class FailingCore:
    async def stream_interviewer_turn(self, **kwargs):
        raise CoreCallError("core unavailable")
        if False:
            yield {}


class FakeGateway:
    async def create_realtime_transcription_session(self, **kwargs):
        return {
            "ws_url": "wss://example.test/realtime",
            "client_secret": "ek_test",
        }


class FakeVerifier:
    def __init__(self, *, score: float = 1.0, raise_score: bool = False) -> None:
        self.score_value = score
        self.raise_score = raise_score

    async def enroll(self, *, pcm16: bytes, sample_rate: int) -> SpeakerProfile:
        if not pcm16:
            raise ValueError("empty")
        return SpeakerProfile(embedding=b"profile")

    async def score(
        self, *, profile: SpeakerProfile, pcm16: bytes, sample_rate: int
    ) -> float:
        if self.raise_score:
            raise RuntimeError("verifier failed")
        return self.score_value


class FakeTranscriber:
    async def connect(self) -> None:
        pass

    async def send_audio(self, pcm16: bytes) -> None:
        pass

    async def clear_audio(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def events(self):
        if False:
            yield {}


def _session(
    *, verifier: FakeVerifier | None = None, turn_commit_delay_ms: int = 0
) -> tuple[LiveSession, FakeWs, FakeCore]:
    ws = FakeWs()
    core = FakeCore()
    claims = TicketClaims(
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        mode="interviewer",
        exp=int(time.time()) + 60,
    )

    async def _factory(_session_info):
        t = FakeTranscriber()
        await t.connect()
        return t

    session = LiveSession(
        ws=ws,  # type: ignore[arg-type]
        claims=claims,
        gateway=FakeGateway(),  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        speaker_verifier=verifier or FakeVerifier(),
        min_transcript_confidence=0.0,
        turn_commit_delay_ms=turn_commit_delay_ms,
        transcriber_factory=_factory,
    )
    return session, ws, core


def _session_with_core(core) -> tuple[LiveSession, FakeWs]:
    ws = FakeWs()
    claims = TicketClaims(
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        mode="interviewer",
        exp=int(time.time()) + 60,
    )
    session = LiveSession(
        ws=ws,  # type: ignore[arg-type]
        claims=claims,
        gateway=FakeGateway(),  # type: ignore[arg-type]
        core=core,  # type: ignore[arg-type]
        speaker_verifier=FakeVerifier(),
        min_transcript_confidence=0.0,
        turn_commit_delay_ms=0,
    )
    return session, ws


@pytest.mark.asyncio
async def test_accepted_primary_speaker_transcript_calls_core_once() -> None:
    session, ws, core = _session(verifier=FakeVerifier(score=0.9))
    session.state.speaker_profile = SpeakerProfile(embedding=b"profile")
    audio = b"\x00\x01" * 24_000

    await session._handle_completed_transcript(transcript="hello", audio=audio)
    assert session.state.current_task is not None
    await session.state.current_task

    assert len(core.calls) == 1
    assert core.calls[0]["transcript"] == "hello"
    assert [m["type"] for m in ws.sent] == [
        "user_speech_stopped",
        "final_transcript",
        "assistant_token",
        "assistant_done",
    ]


@pytest.mark.asyncio
async def test_rejected_speaker_transcript_does_not_call_core() -> None:
    session, ws, core = _session(verifier=FakeVerifier(score=0.1))
    session.state.speaker_profile = SpeakerProfile(embedding=b"profile")
    audio = b"\x00\x01" * 24_000

    await session._handle_completed_transcript(transcript="hello", audio=audio)

    assert core.calls == []
    assert [m["type"] for m in ws.sent] == ["user_speech_stopped", "turn_ignored"]
    assert ws.sent[-1] == {"type": "turn_ignored", "reason": "speaker_mismatch"}


@pytest.mark.asyncio
async def test_transcript_is_ignored_until_calibration_finishes() -> None:
    session, ws, core = _session()
    audio = b"\x00\x01" * 24_000

    await session._handle_completed_transcript(transcript="hello", audio=audio)

    assert core.calls == []
    assert [m["type"] for m in ws.sent] == ["user_speech_stopped", "turn_ignored"]
    assert ws.sent[-1] == {
        "type": "turn_ignored",
        "reason": "missing_speaker_profile",
    }


@pytest.mark.asyncio
async def test_speaker_verifier_failure_fails_closed() -> None:
    session, ws, core = _session(verifier=FakeVerifier(raise_score=True))
    session.state.speaker_profile = SpeakerProfile(embedding=b"profile")
    audio = b"\x00\x01" * 24_000

    await session._handle_completed_transcript(transcript="hello", audio=audio)

    assert core.calls == []
    assert [m["type"] for m in ws.sent] == ["user_speech_stopped", "turn_ignored"]
    assert ws.sent[-1] == {
        "type": "turn_ignored",
        "reason": "speaker_verifier_error",
    }


@pytest.mark.asyncio
async def test_realtime_vad_stop_does_not_immediately_emit_checking() -> None:
    session, ws, _core = _session()

    await session._handle_realtime_event({"type": "input_audio_buffer.speech_started"})
    await session._handle_realtime_event({"type": "input_audio_buffer.speech_stopped"})

    assert [m["type"] for m in ws.sent] == ["user_speech_started"]


@pytest.mark.asyncio
async def test_short_pause_fragments_are_merged_before_core_call() -> None:
    session, _ws, core = _session(
        verifier=FakeVerifier(score=0.9),
        turn_commit_delay_ms=25,
    )
    session.state.speaker_profile = SpeakerProfile(embedding=b"profile")
    audio = b"\x00\x01" * 12_000

    await session._handle_completed_transcript(transcript="hello", audio=audio)
    await session._handle_realtime_event({"type": "input_audio_buffer.speech_started"})
    await session._handle_completed_transcript(transcript="world", audio=audio)

    assert core.calls == []
    assert session.state.pending_turn_task is None
    await session._handle_realtime_event({"type": "input_audio_buffer.speech_stopped"})
    assert session.state.pending_turn_task is not None
    await session.state.pending_turn_task
    assert session.state.current_task is not None
    await session.state.current_task

    assert len(core.calls) == 1
    assert core.calls[0]["transcript"] == "hello world"


@pytest.mark.asyncio
async def test_duplicate_transcription_item_is_ignored() -> None:
    session, _ws, core = _session(verifier=FakeVerifier(score=0.9))
    session.state.speaker_profile = SpeakerProfile(embedding=b"profile")
    audio = b"\x00\x01" * 24_000
    session.state.last_turn_audio = audio

    await session._handle_realtime_event(
        {"type": "input_audio_buffer.committed", "item_id": "item_1"}
    )
    await session._handle_realtime_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item_1",
            "transcript": "hello",
        }
    )
    assert session.state.current_task is not None
    await session.state.current_task
    await session._handle_realtime_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item_1",
            "transcript": "hello",
        }
    )

    assert len(core.calls) == 1
    assert core.calls[0]["transcript"] == "hello"


@pytest.mark.asyncio
async def test_duplicate_audio_transcript_is_ignored_even_with_new_item() -> None:
    session, _ws, core = _session(verifier=FakeVerifier(score=0.9))
    session.state.speaker_profile = SpeakerProfile(embedding=b"profile")
    audio = b"\x00\x01" * 24_000

    for item_id in ("item_1", "item_2"):
        session.state.last_turn_audio = audio
        await session._handle_realtime_event(
            {"type": "input_audio_buffer.committed", "item_id": item_id}
        )
        await session._handle_realtime_event(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": item_id,
                "transcript": "hello",
            }
        )
        if session.state.current_task is not None:
            await session.state.current_task

    assert len(core.calls) == 1
    assert core.calls[0]["transcript"] == "hello"


@pytest.mark.asyncio
async def test_core_stream_failure_sends_error_frame() -> None:
    session, ws = _session_with_core(FailingCore())

    await session._run_core_turn(transcript="hello", voice={})

    assert ws.sent == [
        {"type": "error", "message": "interviewer stream failed"}
    ]


@pytest.mark.asyncio
async def test_active_turn_audio_is_capped_by_max_turn_seconds() -> None:
    session, _ws, _core = _session()
    session.max_turn_seconds = 1
    session.state.sample_rate = 24_000
    session.state.collecting_turn = True
    session.state.active_turn_audio.extend(b"\x00\x01" * 48_000)

    session._trim_active_turn_audio()

    assert len(session.state.active_turn_audio) == 48_000


@pytest.mark.asyncio
async def test_calibration_commit_builds_profile_and_ready_state() -> None:
    session, ws, _core = _session()

    await session._handle_text_frame('{"type":"calibration_start"}')
    await session._handle_audio(b"\x00\x01" * 24_000)
    await session._handle_text_frame('{"type":"calibration_commit"}')

    assert session.state.speaker_profile is not None
    assert [m["type"] for m in ws.sent][-2:] == ["calibration_ready", "ready"]
    await session.close()
