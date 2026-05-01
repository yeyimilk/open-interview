import { Loader2, Mic, MicOff, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "../../api/client";
import { cn } from "../../lib/cn";
import { Button } from "../ui/button";

interface Props {
  onTranscript: (text: string) => void;
  disabled?: boolean;
  language?: string;
}

type Phase = "idle" | "recording" | "transcribing";

const PREFERRED_MIMES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
  "audio/wav",
];

function pickMime(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const m of PREFERRED_MIMES) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

export function VoiceInput({ onTranscript, disabled, language }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAtRef = useRef<number>(0);
  const tickerRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const cancelRef = useRef(false);

  function teardown() {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    if (tickerRef.current !== null) clearInterval(tickerRef.current);
    tickerRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    analyserRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
    setLevel(0);
    setElapsed(0);
  }

  useEffect(() => () => teardown(), []);

  // Press ESC while recording to cancel.
  useEffect(() => {
    if (phase !== "recording") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        cancelRef.current = true;
        recorderRef.current?.stop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase]);

  async function start() {
    if (phase !== "idle") return;
    const mime = pickMime();
    if (!mime || typeof navigator.mediaDevices?.getUserMedia !== "function") {
      toast.error("Audio not supported", {
        description: "Your browser does not support microphone capture.",
      });
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      toast.error("Microphone denied", {
        description:
          "Allow microphone access in your browser to use voice input.",
      });
      return;
    }
    cancelRef.current = false;
    streamRef.current = stream;

    // Volume meter via Web Audio
    try {
      const Ctx =
        (window as any).AudioContext || (window as any).webkitAudioContext;
      const ctx: AudioContext = new Ctx();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      analyserRef.current = analyser;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / buf.length);
        setLevel(Math.min(1, rms * 4));
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch {
      /* meter is best-effort */
    }

    const rec = new MediaRecorder(stream, { mimeType: mime });
    recorderRef.current = rec;
    chunksRef.current = [];
    rec.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };
    rec.onstop = async () => {
      const cancelled = cancelRef.current;
      // Pull pieces before teardown frees them.
      const blob = new Blob(chunksRef.current, { type: mime });
      teardown();
      if (cancelled || blob.size === 0) {
        setPhase("idle");
        return;
      }
      setPhase("transcribing");
      try {
        const { text } = await api.transcribeAudio(blob, language);
        if (text.trim()) onTranscript(text.trim());
        else
          toast.info("No speech detected", {
            description: "Try again — speak a little closer to the mic.",
          });
      } catch (e) {
        toast.error("Transcription failed", {
          description: (e as Error).message,
        });
      } finally {
        setPhase("idle");
      }
    };
    rec.start();
    startedAtRef.current = Date.now();
    setElapsed(0);
    tickerRef.current = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
    }, 250);
    setPhase("recording");
  }

  function stop() {
    if (phase !== "recording") return;
    cancelRef.current = false;
    recorderRef.current?.stop();
  }

  if (phase === "transcribing") {
    return (
      <Button
        type="button"
        variant="ghost"
        className="h-[60px] px-3"
        disabled
        aria-label="Transcribing"
      >
        <Loader2 className="h-4 w-4 animate-spin" />
      </Button>
    );
  }

  if (phase === "recording") {
    const mins = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const secs = String(elapsed % 60).padStart(2, "0");
    return (
      <button
        type="button"
        onClick={stop}
        className="h-[60px] px-3 rounded-md bg-destructive text-destructive-foreground hover:bg-destructive/90 inline-flex items-center gap-2 transition-colors"
        title="Stop recording (or press ESC to cancel)"
      >
        <span className="relative grid place-items-center h-7 w-7">
          <span
            className="absolute inset-0 rounded-full bg-white/30"
            style={{
              transform: `scale(${0.6 + level * 1.6})`,
              transition: "transform 60ms linear",
            }}
          />
          <Square className="h-3.5 w-3.5 fill-current relative z-[1]" />
        </span>
        <span className="text-xs tabular-nums">
          {mins}:{secs}
        </span>
      </button>
    );
  }

  return (
    <Button
      type="button"
      variant="outline"
      className={cn("h-[60px] px-3")}
      onClick={start}
      disabled={disabled}
      title="Hold a thought to dictate (mic)"
      aria-label="Record voice"
    >
      {disabled ? (
        <MicOff className="h-4 w-4" />
      ) : (
        <Mic className="h-4 w-4" />
      )}
    </Button>
  );
}
