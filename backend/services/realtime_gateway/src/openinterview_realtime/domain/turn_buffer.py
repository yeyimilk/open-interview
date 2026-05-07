from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PendingTurnCandidate:
    sequence: int
    transcript: str
    audio: bytes
    item_ids: list[str]
    part_count: int
    logprobs: object


@dataclass
class PendingTurnBuffer:
    transcript_parts: list[str] = field(default_factory=list)
    item_ids: list[str] = field(default_factory=list)
    audio: bytearray = field(default_factory=bytearray)
    logprobs: list[object] = field(default_factory=list)
    sequence: int = 0

    @property
    def has_parts(self) -> bool:
        return bool(self.transcript_parts)

    @property
    def part_count(self) -> int:
        return len(self.transcript_parts)

    @property
    def non_empty_item_ids(self) -> list[str]:
        return [item_id for item_id in self.item_ids if item_id]

    def add(
        self,
        *,
        transcript: str,
        audio: bytes,
        item_id: str | None = None,
        logprobs: object = None,
    ) -> None:
        self.transcript_parts.append(transcript)
        self.item_ids.append(item_id or "")
        self.audio.extend(audio)
        if isinstance(logprobs, list):
            self.logprobs.extend(logprobs)

    def pop_candidate(self) -> PendingTurnCandidate:
        self.sequence += 1
        candidate = PendingTurnCandidate(
            sequence=self.sequence,
            transcript=" ".join(self.transcript_parts).strip(),
            audio=bytes(self.audio),
            item_ids=self.non_empty_item_ids,
            part_count=self.part_count,
            logprobs=list(self.logprobs) if self.logprobs else None,
        )
        self.clear_parts()
        return candidate

    def clear_parts(self) -> None:
        self.transcript_parts.clear()
        self.item_ids.clear()
        self.audio.clear()
        self.logprobs.clear()

    def clear(self, *, reset_sequence: bool = False) -> None:
        self.clear_parts()
        if reset_sequence:
            self.sequence = 0
