import { Mic, MicOff, Square, Loader2, Info, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ChatMessageOut, postMultipartSSE } from "../../api/client";
import { cn } from "../../lib/cn";
import { ChatBubble, UIMessage, VoiceMeta } from "./StreamingChat";

interface Props {
  initialMessages: ChatMessageOut[];
  endpoint: string;
  onAfterSend?: () => void;
  language?: string;
  disabled?: boolean;
}

type Phase = "idle" | "recording" | "uploading";

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

export function AudioStreamingChat({
  initialMessages,
  endpoint,
  onAfterSend,
  language,
  disabled,
}: Props) {
  const [messages, setMessages] = useState<UIMessage[]>(
    initialMessages.map((m) => ({
      role: m.role,
      content: m.content,
      voice: (m.meta?.voice as VoiceMeta) ?? null,
    }))
  );
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [bars, setBars] = useState<number[]>(() => new Array(28).fill(0.05));

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAtRef = useRef<number>(0);
  const tickerRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const cancelRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Refresh from props whenever the parent reloads server-side messages.
  useEffect(() => {
    setMessages(
      initialMessages.map((m) => ({
        role: m.role,
        content: m.content,
        voice: (m.meta?.voice as VoiceMeta) ?? null,
      }))
    );
  }, [initialMessages]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, phase]);

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
    setBars(new Array(28).fill(0.05));
  }

  useEffect(() => () => teardown(), []);

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
    if (phase !== "idle" || disabled) return;
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
    } catch {
      toast.error("Microphone denied", {
        description: "Allow microphone access to record your answer.",
      });
      return;
    }
    cancelRef.current = false;
    streamRef.current = stream;

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
        const lvl = Math.min(1, rms * 4);
        setLevel(lvl);
        setBars((prev) => {
          const next = prev.slice(1);
          next.push(Math.max(0.05, lvl));
          return next;
        });
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch {
      /* meter best-effort */
    }

    const rec = new MediaRecorder(stream, { mimeType: mime });
    recorderRef.current = rec;
    chunksRef.current = [];
    rec.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };
    rec.onstop = async () => {
      const cancelled = cancelRef.current;
      const blob = new Blob(chunksRef.current, { type: mime });
      teardown();
      if (cancelled || blob.size === 0) {
        setPhase("idle");
        return;
      }
      setPhase("uploading");

      // Optimistically push placeholder bubbles so the UX matches text mode:
      // a "you" bubble (transcript fills in from the voice event) and an
      // "interviewer" bubble that streams tokens in.
      setMessages((m) => [
        ...m,
        { role: "user", content: "", pending: true },
        { role: "assistant", content: "", pending: true },
      ]);

      const fd = new FormData();
      const ext = (mime.split("/")[1] || "webm").split(";")[0];
      fd.append("audio", blob, `clip.${ext}`);
      if (language) fd.append("language", language);

      try {
        await postMultipartSSE(endpoint, fd, (ev) => {
          if (ev.event === "voice") {
            const data = ev.data as any;
            const transcript = String(data?.transcript || "");
            const voice: VoiceMeta = (data?.voice as VoiceMeta) || {};
            setMessages((m) => {
              const copy = [...m];
              // The user bubble is the second-to-last (assistant is last).
              const userIdx = copy.length - 2;
              if (userIdx >= 0 && copy[userIdx].role === "user") {
                copy[userIdx] = {
                  ...copy[userIdx],
                  content: transcript,
                  voice,
                  pending: false,
                };
              }
              return copy;
            });
          } else if (ev.event === "token") {
            const piece = (ev.data as any)?.content || "";
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              if (last && last.role === "assistant" && last.pending) {
                copy[copy.length - 1] = {
                  ...last,
                  content: last.content + piece,
                };
              }
              return copy;
            });
          } else if (ev.event === "done") {
            const full = (ev.data as any)?.content || "";
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              if (last && last.role === "assistant" && last.pending) {
                copy[copy.length - 1] = {
                  role: "assistant",
                  content: full || last.content,
                };
              }
              return copy;
            });
          } else if (ev.event === "error") {
            const msg = (ev.data as any)?.message || "stream error";
            toast.error("Audio turn failed", { description: msg });
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              if (last && last.role === "assistant" && last.pending) {
                copy[copy.length - 1] = {
                  role: "assistant",
                  content: `(error: ${msg})`,
                };
              }
              return copy;
            });
          }
        });
      } catch (e) {
        toast.error("Audio turn failed", {
          description: (e as Error).message,
        });
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          if (last && last.role === "assistant" && last.pending) {
            copy[copy.length - 1] = {
              role: "assistant",
              content: `(error: ${(e as Error).message})`,
            };
          }
          return copy;
        });
      } finally {
        setPhase("idle");
        onAfterSend?.();
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

  function cancel() {
    if (phase !== "recording") return;
    cancelRef.current = true;
    recorderRef.current?.stop();
  }

  return (
    <div className="flex flex-col h-[70vh] min-h-[420px]">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-xl border bg-muted/30 p-3 md:p-4 space-y-3"
      >
        {messages.length === 0 ? (
          <div className="grid h-full place-items-center">
            <div className="max-w-md text-center space-y-2">
              <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary">
                <Mic className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-medium">Voice mode</h3>
              <p className="text-xs text-muted-foreground">
                Press the record button below and speak your answer. We'll
                transcribe it, score the content, and analyse delivery
                (pace, fillers, confidence).
              </p>
            </div>
          </div>
        ) : (
          messages.map((m, i) => <ChatBubble key={i} message={m} />)
        )}
      </div>

      <RecorderBar
        phase={phase}
        elapsed={elapsed}
        level={level}
        bars={bars}
        disabled={disabled}
        onStart={start}
        onStop={stop}
        onCancel={cancel}
      />
    </div>
  );
}

function RecorderBar({
  phase,
  elapsed,
  level,
  bars,
  disabled,
  onStart,
  onStop,
  onCancel,
}: {
  phase: Phase;
  elapsed: number;
  level: number;
  bars: number[];
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
  onCancel: () => void;
}) {
  const mins = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const secs = String(elapsed % 60).padStart(2, "0");

  if (phase === "uploading") {
    return (
      <div className="mt-3 rounded-xl border bg-muted/40 px-4 py-3 flex items-center gap-3">
        <Loader2 className="h-4 w-4 animate-spin text-primary" />
        <div className="text-sm">
          <div className="font-medium">Analysing your answer...</div>
          <div className="text-xs text-muted-foreground">
            Transcribing, scoring delivery, and preparing the next question.
          </div>
        </div>
      </div>
    );
  }

  if (phase === "recording") {
    return (
      <div className="mt-3 rounded-xl border-2 border-destructive/40 bg-destructive/5 px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="relative grid place-items-center h-9 w-9 shrink-0">
            <span
              className="absolute inset-0 rounded-full bg-destructive/30"
              style={{
                transform: `scale(${0.8 + level * 1.4})`,
                transition: "transform 60ms linear",
              }}
            />
            <span className="absolute inset-1 rounded-full bg-destructive" />
            <span className="relative z-[1] h-2.5 w-2.5 rounded-full bg-white animate-pulse" />
          </span>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1 text-destructive font-medium">
                <span className="h-1.5 w-1.5 rounded-full bg-destructive animate-pulse" />
                REC
              </span>
              <span className="tabular-nums text-foreground">
                {mins}:{secs}
              </span>
              <span className="opacity-60">·</span>
              <span>ESC to cancel</span>
            </div>
            <Waveform bars={bars} />
          </div>

          <button
            type="button"
            onClick={onCancel}
            title="Discard recording"
            className="grid h-9 w-9 place-items-center rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onStop}
            title="Stop and submit"
            className="inline-flex items-center gap-2 rounded-md bg-destructive text-destructive-foreground px-4 h-9 hover:bg-destructive/90 transition-colors"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
            <span className="text-sm font-medium">Stop</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-xl border bg-card px-4 py-3 flex items-center gap-3">
      <button
        type="button"
        onClick={onStart}
        disabled={disabled}
        className={cn(
          "grid h-12 w-12 place-items-center rounded-full shrink-0 transition-all",
          disabled
            ? "bg-muted text-muted-foreground"
            : "bg-primary text-primary-foreground hover:scale-105 hover:shadow-lg shadow-md ring-4 ring-primary/15"
        )}
        title={disabled ? "Recording disabled" : "Tap to record your answer"}
      >
        {disabled ? (
          <MicOff className="h-5 w-5" />
        ) : (
          <Mic className="h-5 w-5" />
        )}
      </button>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium">
          {disabled ? "Voice mode unavailable" : "Tap to record your answer"}
        </div>
        <div className="text-xs text-muted-foreground inline-flex items-center gap-1">
          <Info className="h-3 w-3" />
          Speak naturally. We'll score pace, fillers, and confidence.
        </div>
      </div>
    </div>
  );
}

function Waveform({ bars }: { bars: number[] }) {
  return (
    <div className="mt-1 flex items-end gap-[2px] h-6">
      {bars.map((b, i) => (
        <span
          key={i}
          className="w-[3px] rounded-sm bg-destructive/80"
          style={{
            height: `${Math.max(8, Math.min(100, b * 100))}%`,
            opacity: 0.4 + (i / bars.length) * 0.6,
            transition: "height 80ms linear",
          }}
        />
      ))}
    </div>
  );
}
