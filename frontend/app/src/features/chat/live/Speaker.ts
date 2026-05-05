/**
 * Browser-side TTS using the Web Speech API.
 *
 * v1 ships speech synthesis on the client so we don't need a server TTS
 * dependency. The realtime gateway streams *text* tokens; this Speaker chunks
 * them by sentence and queues `SpeechSynthesisUtterance`s so the assistant
 * starts talking while the rest is still streaming.
 *
 * When server TTS is added later, we swap this module for a
 * MediaSource/AudioBuffer player that consumes binary frames from the WS;
 * the consumer API stays the same.
 */

const BOUNDARY_RE = /([.!?…]+["')\]]?\s+|\n+)/;

export interface SpeakerOptions {
  voiceName?: string | null;
  rate?: number;
  pitch?: number;
  volume?: number;
}

export class Speaker {
  private buf = "";
  private muted = false;
  private opts: Required<SpeakerOptions>;
  private get supported(): boolean {
    return typeof window !== "undefined" && "speechSynthesis" in window;
  }

  constructor(opts: SpeakerOptions = {}) {
    this.opts = {
      voiceName: opts.voiceName ?? null,
      rate: opts.rate ?? 1.0,
      pitch: opts.pitch ?? 1.0,
      volume: opts.volume ?? 1.0,
    };
  }

  setMuted(m: boolean): void {
    this.muted = m;
    if (m) this.cancel();
  }

  /** True when the browser is currently playing or has queued an utterance.
   *  We use this to hard-gate VAD so the mic doesn't pick up the agent's
   *  own voice and treat it as user speech (the classic "AI talks to
   *  itself" loop). */
  isPlaying(): boolean {
    if (!this.supported) return false;
    try {
      return (
        window.speechSynthesis.speaking || window.speechSynthesis.pending
      );
    } catch {
      return false;
    }
  }

  push(piece: string): void {
    if (!piece) return;
    this.buf += piece;
    let m: RegExpMatchArray | null;
    while ((m = this.buf.match(BOUNDARY_RE))) {
      const idx = (m.index ?? 0) + m[0].length;
      const sentence = this.buf.slice(0, idx).trim();
      this.buf = this.buf.slice(idx);
      if (sentence) this.enqueue(sentence);
    }
  }

  flush(): void {
    const tail = this.buf.trim();
    this.buf = "";
    if (tail) this.enqueue(tail);
  }

  cancel(): void {
    this.buf = "";
    if (this.supported) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* ignore */
      }
    }
  }

  private enqueue(text: string): void {
    if (this.muted || !this.supported) return;
    try {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = this.opts.rate;
      u.pitch = this.opts.pitch;
      u.volume = this.opts.volume;
      if (this.opts.voiceName) {
        const v = window.speechSynthesis
          .getVoices()
          .find((x) => x.name === this.opts.voiceName);
        if (v) u.voice = v;
      }
      window.speechSynthesis.speak(u);
    } catch {
      /* ignore */
    }
  }
}
