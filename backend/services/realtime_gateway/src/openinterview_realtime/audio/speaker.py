from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SpeakerVerificationError(Exception):
    pass


@dataclass(frozen=True)
class SpeakerProfile:
    embedding: object
    quality: float | None = None
    duration_s: float | None = None


class SpeakerVerifier(Protocol):
    async def enroll(self, *, pcm16: bytes, sample_rate: int) -> SpeakerProfile: ...

    async def score(
        self, *, profile: SpeakerProfile, pcm16: bytes, sample_rate: int
    ) -> float: ...


class SpeechBrainSpeakerVerifier:
    """ECAPA-TDNN speaker verification with lazy optional imports.

    The realtime package can be installed without the heavy speaker stack for
    tests/local API work. Live calibration fails closed if this backend is used
    without installing the optional `speaker` dependencies.
    """

    def __init__(
        self,
        *,
        source: str = "speechbrain/spkrec-ecapa-voxceleb",
        savedir: str = "pretrained_models/spkrec-ecapa-voxceleb",
    ) -> None:
        self._source = source
        self._savedir = savedir
        self._verifier = None

    @staticmethod
    def check_dependencies() -> None:
        try:
            import numpy  # noqa: F401
            import torch  # noqa: F401
            import torchaudio  # noqa: F401
            import speechbrain  # noqa: F401
        except Exception as e:  # noqa: BLE001
            raise SpeakerVerificationError(
                "install openinterview-realtime[speaker] for speaker verification"
            ) from e

    async def enroll(self, *, pcm16: bytes, sample_rate: int) -> SpeakerProfile:
        waveform = await self._waveform(pcm16=pcm16, sample_rate=sample_rate)
        embeddings = self._embeddings_for_waveform(waveform)
        quality = self._profile_quality(embeddings)
        if quality is not None and quality < 0.15:
            raise SpeakerVerificationError("calibration speech is not consistent enough")
        return SpeakerProfile(
            embedding=embeddings,
            quality=quality,
            duration_s=float(waveform.numel()) / 16000,
        )

    async def score(
        self, *, profile: SpeakerProfile, pcm16: bytes, sample_rate: int
    ) -> float:
        waveform = await self._waveform(pcm16=pcm16, sample_rate=sample_rate)
        candidates = self._embeddings_for_waveform(waveform)
        try:
            import torch
        except Exception as e:  # noqa: BLE001
            raise SpeakerVerificationError(
                "torch is required for speaker verification"
            ) from e

        refs = profile.embedding
        if hasattr(refs, "detach"):
            refs = [refs]
        if not isinstance(refs, list) or not refs:
            raise SpeakerVerificationError("invalid speaker profile")
        scores: list[float] = []
        for ref in refs:
            if not hasattr(ref, "detach"):
                continue
            for emb in candidates:
                score = torch.nn.functional.cosine_similarity(
                    ref.reshape(1, -1), emb.reshape(1, -1)
                )
                scores.append(float(score.item()))
        if not scores:
            raise SpeakerVerificationError("invalid speaker profile")
        scores.sort(reverse=True)
        top = scores[: min(3, len(scores))]
        return sum(top) / len(top)

    async def _waveform(self, *, pcm16: bytes, sample_rate: int):
        if len(pcm16) < sample_rate:
            raise SpeakerVerificationError("not enough calibration audio")
        try:
            import numpy as np
            import torch
            import torchaudio.functional as F
            from speechbrain.inference.speaker import SpeakerRecognition
        except Exception as e:  # noqa: BLE001
            raise SpeakerVerificationError(
                "install openinterview-realtime[speaker] for speaker verification"
            ) from e

        if self._verifier is None:
            self._verifier = SpeakerRecognition.from_hparams(
                source=self._source,
                savedir=self._savedir,
                run_opts={"device": "cpu"},
            )

        arr = np.frombuffer(pcm16, dtype="<i2").astype("float32") / 32768.0
        if arr.size == 0:
            raise SpeakerVerificationError("empty audio")
        arr = _trim_silence(arr, sample_rate)
        if arr.size < int(sample_rate * 0.5):
            raise SpeakerVerificationError("not enough speech audio")
        signal = torch.from_numpy(arr).unsqueeze(0)
        if sample_rate != 16000:
            signal = F.resample(signal, orig_freq=sample_rate, new_freq=16000)
        return signal.squeeze(0)

    def _embedding_for_segment(self, segment):
        return (
            self._verifier.encode_batch(segment, normalize=False)
            .squeeze()
            .detach()
            .cpu()
        )

    def _embeddings_for_waveform(self, waveform) -> list[object]:
        sample_rate = 16000
        window = int(sample_rate * 1.6)
        hop = int(sample_rate * 0.8)
        min_window = int(sample_rate * 0.8)
        embeddings = [self._embedding_for_segment(waveform)]
        if waveform.numel() <= window:
            return embeddings
        for start in range(0, max(1, waveform.numel() - min_window + 1), hop):
            end = min(waveform.numel(), start + window)
            if end - start < min_window:
                continue
            embeddings.append(self._embedding_for_segment(waveform[start:end]))
        return embeddings

    def _profile_quality(self, embeddings: list[object]) -> float | None:
        if len(embeddings) < 3:
            return None
        try:
            import torch
        except Exception as e:  # noqa: BLE001
            raise SpeakerVerificationError(
                "torch is required for speaker verification"
            ) from e
        full = embeddings[0]
        scores: list[float] = []
        for emb in embeddings[1:]:
            score = torch.nn.functional.cosine_similarity(
                full.reshape(1, -1), emb.reshape(1, -1)
            )
            scores.append(float(score.item()))
        if not scores:
            return None
        return sum(scores) / len(scores)


class AcceptAllSpeakerVerifier:
    """Explicit test/dev verifier. Do not use for production live mode."""

    async def enroll(self, *, pcm16: bytes, sample_rate: int) -> SpeakerProfile:
        if not pcm16:
            raise SpeakerVerificationError("empty calibration audio")
        return SpeakerProfile(embedding=b"accept-all")

    async def score(
        self, *, profile: SpeakerProfile, pcm16: bytes, sample_rate: int
    ) -> float:
        return 1.0 if pcm16 else 0.0


def build_speaker_verifier(backend: str) -> SpeakerVerifier:
    normalized = (backend or "speechbrain").lower()
    if normalized == "accept-all":
        return AcceptAllSpeakerVerifier()
    SpeechBrainSpeakerVerifier.check_dependencies()
    return SpeechBrainSpeakerVerifier()


def _trim_silence(arr, sample_rate: int):
    """Trim leading/trailing quiet frames before computing speaker embeddings."""
    if arr.size == 0:
        return arr
    frame = max(1, int(sample_rate * 0.03))
    hop = max(1, int(sample_rate * 0.01))
    if arr.size <= frame:
        return arr

    import numpy as np

    rms: list[float] = []
    starts = range(0, arr.size - frame + 1, hop)
    for start in starts:
        window = arr[start : start + frame]
        rms.append(float(np.sqrt(np.mean(window * window))))
    if not rms:
        return arr

    levels = np.asarray(rms, dtype="float32")
    noise_floor = float(np.percentile(levels, 20))
    threshold = max(0.006, min(0.04, noise_floor * 2.5 + 0.002))
    voiced = np.flatnonzero(levels >= threshold)
    if voiced.size == 0:
        return arr[:0]

    pad_before = int(sample_rate * 0.15)
    pad_after = int(sample_rate * 0.2)
    start = max(0, int(voiced[0]) * hop - pad_before)
    end = min(arr.size, int(voiced[-1]) * hop + frame + pad_after)
    trimmed = arr[start:end]
    min_samples = int(sample_rate * 0.5)
    if trimmed.size < min_samples:
        return arr
    return np.ascontiguousarray(trimmed)
