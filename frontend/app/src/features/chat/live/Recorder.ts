/**
 * Live PCM capture pipeline.
 *
 * The realtime gateway and OpenAI Realtime transcription expect 24 kHz mono
 * little-endian PCM16. Browser capture usually arrives as Float32 at the
 * device sample rate, so this module keeps a small Web Audio graph for level
 * metering and PCM conversion. Turn detection no longer happens here.
 */

const TARGET_SAMPLE_RATE = 24_000;
const CHANNELS = 1;
const AUDIO_FORMAT = "pcm16" as const;

export interface CaptureHandlers {
  onLevel?: (rms: number, nowMs: number) => void;
  onAudio?: (chunk: ArrayBuffer) => void;
  onError?: (err: Error) => void;
}

export interface CaptureHandle {
  audioFormat: typeof AUDIO_FORMAT;
  sampleRate: typeof TARGET_SAMPLE_RATE;
  channels: typeof CHANNELS;
  stop: () => void;
}

export async function startCapture(
  handlers: CaptureHandlers
): Promise<CaptureHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: CHANNELS,
    } as MediaTrackConstraints,
  });

  const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
  if (!Ctx) {
    stream.getTracks().forEach((t) => t.stop());
    throw new Error("Browser does not support Web Audio capture");
  }

  const ctx: AudioContext = new Ctx();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  src.connect(analyser);

  const processor = ctx.createScriptProcessor(4096, CHANNELS, CHANNELS);
  const mutedSink = ctx.createGain();
  mutedSink.gain.value = 0;
  src.connect(processor);
  processor.connect(mutedSink);
  mutedSink.connect(ctx.destination);

  const meterBuf = new Uint8Array(analyser.fftSize);
  let raf = 0;
  const tick = () => {
    analyser.getByteTimeDomainData(meterBuf);
    let sum = 0;
    for (let i = 0; i < meterBuf.length; i++) {
      const v = (meterBuf[i] - 128) / 128;
      sum += v * v;
    }
    handlers.onLevel?.(Math.sqrt(sum / meterBuf.length), performance.now());
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);

  processor.onaudioprocess = (event) => {
    try {
      const input = event.inputBuffer.getChannelData(0);
      const pcm = floatToPcm16(input, ctx.sampleRate);
      if (pcm.byteLength > 0) handlers.onAudio?.(pcm);
    } catch (e) {
      handlers.onError?.(e as Error);
    }
  };

  function stop() {
    processor.onaudioprocess = null;
    if (raf) cancelAnimationFrame(raf);
    try {
      processor.disconnect();
      mutedSink.disconnect();
      analyser.disconnect();
      src.disconnect();
    } catch {
      /* ignore */
    }
    stream.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => {});
  }

  return {
    audioFormat: AUDIO_FORMAT,
    sampleRate: TARGET_SAMPLE_RATE,
    channels: CHANNELS,
    stop,
  };
}

function floatToPcm16(input: Float32Array, inputRate: number): ArrayBuffer {
  if (input.length === 0 || inputRate <= 0) return new ArrayBuffer(0);
  const outLength = Math.max(
    1,
    Math.round((input.length * TARGET_SAMPLE_RATE) / inputRate)
  );
  const out = new Int16Array(outLength);
  const scale = input.length / outLength;
  for (let i = 0; i < outLength; i++) {
    const pos = i * scale;
    const idx = Math.min(input.length - 1, Math.floor(pos));
    const frac = pos - idx;
    const next = Math.min(input.length - 1, idx + 1);
    const sample = input[idx] * (1 - frac) + input[next] * frac;
    const clamped = Math.max(-1, Math.min(1, sample));
    out[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return out.buffer;
}
