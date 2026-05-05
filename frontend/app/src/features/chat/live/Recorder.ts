/**
 * Live capture pipeline.
 *
 * We separate two concerns that used to live in one MediaRecorder:
 *
 *   - "Always-on capture": getUserMedia + AudioContext analyser. This is
 *     what powers the VAD level meter — it runs from the moment the live
 *     tab is open until it's closed. The audio stream itself is never
 *     interrupted.
 *
 *   - "Per-utterance recording": a *fresh* MediaRecorder is started when
 *     VAD detects speech and stopped when VAD detects end-of-utterance.
 *     This gives us a self-contained webm/opus blob (with a valid header)
 *     for each turn so the gateway's STT can decode it. Reusing one
 *     MediaRecorder across turns would only put the WebM header on the
 *     very first chunk, breaking every subsequent turn.
 */

const PREFERRED_MIMES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

export function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const m of PREFERRED_MIMES) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

export interface CaptureHandlers {
  onLevel?: (rms: number, nowMs: number) => void;
  onError?: (err: Error) => void;
}

export interface CaptureHandle {
  /** Negotiated container/codec for this session. */
  mime: string;
  /** Begin recording the current utterance. Safe to call repeatedly; will
   *  no-op if a recorder is already running. */
  startUtterance: () => void;
  /** Stop the current utterance recorder and resolve with the resulting
   *  blob. Resolves with `null` if no recorder is running. */
  endUtterance: () => Promise<Blob | null>;
  /** Tear everything down (mic + analyser). */
  stop: () => void;
}

export async function startCapture(
  handlers: CaptureHandlers
): Promise<CaptureHandle> {
  const mime = pickMime();
  if (!mime) throw new Error("Browser does not support audio capture");
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    } as MediaTrackConstraints,
  });

  // Analyser → drives VAD level callbacks.
  let raf = 0;
  let ctx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  try {
    const Ctx =
      (window as any).AudioContext || (window as any).webkitAudioContext;
    ctx = new Ctx();
    const src = ctx!.createMediaStreamSource(stream);
    analyser = ctx!.createAnalyser();
    analyser.fftSize = 1024;
    src.connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    const tick = () => {
      analyser!.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) {
        const v = (buf[i] - 128) / 128;
        sum += v * v;
      }
      handlers.onLevel?.(Math.sqrt(sum / buf.length), performance.now());
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  } catch {
    /* meter best-effort */
  }

  let recorder: MediaRecorder | null = null;
  let chunks: BlobPart[] = [];

  function startUtterance() {
    if (recorder) return;
    chunks = [];
    const r = new MediaRecorder(stream, { mimeType: mime });
    r.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    r.onerror = (e) => handlers.onError?.(new Error(String(e)));
    // No timeslice → MediaRecorder buffers internally; we get one final
    // dataavailable on stop with a fully-formed webm container.
    r.start();
    recorder = r;
  }

  function endUtterance(): Promise<Blob | null> {
    const r = recorder;
    recorder = null;
    if (!r) return Promise.resolve(null);
    return new Promise<Blob | null>((resolve) => {
      r.onstop = () => {
        const blob = new Blob(chunks, { type: mime });
        chunks = [];
        resolve(blob.size ? blob : null);
      };
      try {
        r.stop();
      } catch {
        resolve(null);
      }
    });
  }

  function stop() {
    try {
      if (recorder && recorder.state !== "inactive") recorder.stop();
    } catch {
      /* ignore */
    }
    recorder = null;
    chunks = [];
    if (raf) cancelAnimationFrame(raf);
    stream.getTracks().forEach((t) => t.stop());
    ctx?.close().catch(() => {});
  }

  return { mime, startUtterance, endUtterance, stop };
}
