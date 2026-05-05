/**
 * Lightweight client-side voice activity detector.
 *
 * We can't ship webrtcvad in the browser cheaply, so we use an energy-based
 * RMS detector with:
 *   - an adaptive noise floor (tracked when we believe the user is silent),
 *   - a startup grace period so background noise isn't detected as speech,
 *   - hangover-style debouncing so brief consonant gaps aren't reported as
 *     end-of-utterance.
 *
 * The detector is poll-driven: feed it `feed(rms, nowMs)` regularly (we do
 * that from the existing AudioContext analyser tick) and react to its
 * `speech_start` / `speech_end` events.
 */

export interface VadEvents {
  onSpeechStart?: () => void;
  onSpeechEnd?: () => void;
}

export interface VadConfig {
  /** Min ratio above noise floor (RMS) to count as speech. */
  thresholdRatio: number;
  /** Hard floor applied on top of adaptive ratio. */
  minThreshold: number;
  /** ms of continuous voice required before we declare speech_start. */
  startMs: number;
  /** ms of continuous silence required before we declare speech_end. */
  endMs: number;
  /** ms after `feed()` first called during which we don't fire events. */
  warmupMs: number;
  /** EMA factor for the noise-floor tracker (0..1). */
  noiseAlpha: number;
  /** When true (assistant is speaking), thresholds + start hangover are
   *  raised so only sustained, loud user speech qualifies as barge-in. */
  speakingMode: boolean;
}

export const DEFAULT_VAD: VadConfig = {
  // Calmer defaults: keyboard clicks, mouse clicks, fan noise, and a stray
  // breath should NOT cross the bar. Real speech easily does.
  thresholdRatio: 3.5,
  minThreshold: 0.03,
  startMs: 280,
  endMs: 1200,
  warmupMs: 700,
  noiseAlpha: 0.05,
  speakingMode: false,
};

const SPEAKING_MODE_THRESHOLD_BOOST = 1.6;
const SPEAKING_MODE_START_MS = 450;

export class Vad {
  private cfg: VadConfig;
  private noise = 0.0;
  private startedAt = 0;
  private inSpeech = false;
  private speechAccumMs = 0;
  private silenceAccumMs = 0;
  private lastFedAt = 0;
  private events: VadEvents;

  constructor(events: VadEvents = {}, cfg: Partial<VadConfig> = {}) {
    this.events = events;
    this.cfg = { ...DEFAULT_VAD, ...cfg };
  }

  reset(): void {
    this.noise = 0;
    this.startedAt = 0;
    this.inSpeech = false;
    this.speechAccumMs = 0;
    this.silenceAccumMs = 0;
    this.lastFedAt = 0;
  }

  setSpeakingMode(on: boolean): void {
    this.cfg.speakingMode = on;
  }

  isSpeaking(): boolean {
    return this.inSpeech;
  }

  feed(rms: number, nowMs: number): void {
    if (!this.startedAt) {
      this.startedAt = nowMs;
      this.lastFedAt = nowMs;
      this.noise = rms;
      return;
    }
    const dt = Math.max(0, nowMs - this.lastFedAt);
    this.lastFedAt = nowMs;

    const warming = nowMs - this.startedAt < this.cfg.warmupMs;
    const boost = this.cfg.speakingMode ? SPEAKING_MODE_THRESHOLD_BOOST : 1.0;
    const threshold = Math.max(
      this.cfg.minThreshold * boost,
      this.noise * this.cfg.thresholdRatio * boost
    );
    const isVoice = rms > threshold;

    if (isVoice) {
      this.speechAccumMs += dt;
      this.silenceAccumMs = 0;
    } else {
      this.silenceAccumMs += dt;
      this.speechAccumMs = 0;
      // Only update noise floor while silent — keeps it from drifting up
      // during a long utterance.
      if (!this.inSpeech) {
        this.noise = this.noise * (1 - this.cfg.noiseAlpha) + rms * this.cfg.noiseAlpha;
      }
    }

    if (warming) return;

    const startMs = this.cfg.speakingMode
      ? Math.max(this.cfg.startMs, SPEAKING_MODE_START_MS)
      : this.cfg.startMs;

    if (!this.inSpeech && this.speechAccumMs >= startMs) {
      this.inSpeech = true;
      this.events.onSpeechStart?.();
    } else if (this.inSpeech && this.silenceAccumMs >= this.cfg.endMs) {
      this.inSpeech = false;
      this.events.onSpeechEnd?.();
    }
  }
}
