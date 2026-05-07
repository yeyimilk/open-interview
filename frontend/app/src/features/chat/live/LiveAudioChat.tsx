import { Mic, MicOff, Radio, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ChatMessageOut } from "../../../api/client";
import { cn } from "../../../lib/cn";
import { ChatBubble, UIMessage, VoiceMeta } from "../StreamingChat";
import { useLiveAudioSession, LiveStatus } from "./useLiveAudioSession";

interface Props {
  sessionId: string;
  initialMessages: ChatMessageOut[];
  onAfterTurn?: () => void;
  disabled?: boolean;
}

export function LiveAudioChat({
  sessionId,
  initialMessages,
  onAfterTurn,
  disabled,
}: Props) {
  const [messages, setMessages] = useState<UIMessage[]>(() =>
    initialMessages.map((m) => ({
      role: m.role,
      content: m.content,
      voice: (m.meta?.voice as VoiceMeta) ?? null,
    }))
  );

  useEffect(() => {
    setMessages(
      initialMessages.map((m) => ({
        role: m.role,
        content: m.content,
        voice: (m.meta?.voice as VoiceMeta) ?? null,
      }))
    );
  }, [initialMessages]);

  const live = useLiveAudioSession({
    sessionId,
    enabled: !disabled,
    onTurnDone: onAfterTurn,
  });

  // Whenever the parent's persisted messages refresh, drop any locally-held
  // completed turns whose assistant text is now in the persisted list.
  // This keeps the bubble visible across the small async gap between
  // `assistant_done` and the parent's `reload()` resolving, without ever
  // rendering it twice.
  useEffect(() => {
    if (live.completedTurns.length === 0) return;
    const persisted = initialMessages
      .filter((m) => m.role === "assistant")
      .map((m) => m.content);
    live.dropPersisted(persisted);
  }, [initialMessages, live.completedTurns.length, live.dropPersisted]);

  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, live.currentTurn, live.completedTurns.length, live.status]);

  const merged: UIMessage[] = [...messages];
  // Render completed (but not-yet-persisted) turns first.
  for (const ct of live.completedTurns) {
    if (ct.userTranscript) {
      merged.push({
        role: "user",
        content: ct.userTranscript,
        voice: ct.voice,
        pending: false,
      });
    }
    if (ct.assistantText) {
      merged.push({
        role: "assistant",
        content: ct.assistantText,
        pending: false,
      });
    }
  }
  // Then the live in-flight turn, if any.
  if (live.currentTurn) {
    if (live.currentTurn.userTranscript) {
      merged.push({
        role: "user",
        content: live.currentTurn.userTranscript,
        voice: live.currentTurn.voice,
        pending: false,
      });
    }
    if (live.currentTurn.assistantText || live.currentTurn.pending) {
      merged.push({
        role: "assistant",
        content: live.currentTurn.assistantText,
        pending: live.currentTurn.pending,
      });
    }
  }

  return (
    <div className="flex flex-col h-[70vh] min-h-[420px]">
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-xl border bg-muted/30 p-3 md:p-4 space-y-3"
      >
        {merged.length === 0 ? <EmptyState /> : merged.map((m, i) => (
          <ChatBubble key={i} message={m} />
        ))}
      </div>

      <LiveBar
        status={live.status}
        error={live.error}
        ignoredReason={live.ignoredReason}
        level={live.micLevel}
        muted={live.muted}
        micPaused={live.micPaused}
        onToggleMute={() => live.setMuted(!live.muted)}
        onToggleMic={() => live.setMicPaused(!live.micPaused)}
      />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="grid h-full place-items-center">
      <div className="max-w-md text-center space-y-2">
        <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-primary/10 text-primary">
          <Radio className="h-5 w-5" />
        </div>
        <h3 className="text-sm font-medium">Live voice mode</h3>
        <p className="text-xs text-muted-foreground">
          First we calibrate to your voice. Then we listen continuously,
          ignore rejected background audio, and stream the interviewer's reply.
        </p>
      </div>
    </div>
  );
}

function statusCopy(
  status: LiveStatus,
  micPaused: boolean,
  ignoredReason: string | null
): {
  label: string;
  hint: string;
} {
  if (micPaused) return { label: "Mic paused", hint: "Tap the mic to resume." };
  switch (status) {
    case "idle":
      return { label: "Idle", hint: "" };
    case "connecting":
      return { label: "Connecting...", hint: "Setting up live audio." };
    case "calibrating":
      return {
        label: "Calibrating voice...",
        hint: "Say a short sentence in your normal interview voice.",
      };
    case "ready":
      return {
        label: "Listening",
        hint: "Just start talking — background audio is ignored.",
      };
    case "user_speaking":
      return {
        label: "Voice detected",
        hint: "Pause when you are done.",
      };
    case "processing_audio":
      return {
        label: "Checking audio...",
        hint: "Confirming speaker and transcript.",
      };
    case "ignored_audio":
      return {
        label: "Audio ignored",
        hint: ignoredHint(ignoredReason),
      };
    case "thinking":
      return {
        label: "Transcribing & thinking...",
        hint: "Got it — preparing a reply.",
      };
    case "speaking":
      return {
        label: "Interviewer is speaking...",
        hint: "Tap the speaker button to mute playback.",
      };
    case "error":
      return { label: "Error", hint: "Reload to retry." };
    case "closed":
      return { label: "Disconnected", hint: "" };
  }
}

function LiveBar({
  status,
  error,
  ignoredReason,
  level,
  muted,
  micPaused,
  onToggleMute,
  onToggleMic,
}: {
  status: LiveStatus;
  error: string | null;
  ignoredReason: string | null;
  level: number;
  muted: boolean;
  micPaused: boolean;
  onToggleMute: () => void;
  onToggleMic: () => void;
}) {
  const { label, hint } = statusCopy(status, micPaused, ignoredReason);
  const dot = statusDot(status, micPaused);

  const showMeter =
    !micPaused &&
    (status === "ready" ||
      status === "calibrating" ||
      status === "user_speaking");

  const barTone = statusBarTone(status);

  return (
    <div
      className={cn(
        "mt-3 rounded-xl border px-4 py-3 flex items-center gap-3",
        barTone
      )}
    >
      <span className="relative grid place-items-center h-9 w-9 shrink-0">
        <span className={cn("h-2.5 w-2.5 rounded-full", dot)} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {showMeter ? (
          <div className="mt-1 h-1.5 w-full rounded bg-muted-foreground/15 overflow-hidden">
            <div
              className={cn(
                "h-full transition-[width] duration-100",
                status === "calibrating"
                  ? "bg-sky-500/70"
                  : status === "user_speaking"
                    ? "bg-red-500/70"
                    : "bg-emerald-500/60"
              )}
              style={{ width: `${Math.min(100, level * 100)}%` }}
            />
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">
            {error ? `Error: ${error}` : hint}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onToggleMute}
        className="grid h-9 w-9 place-items-center rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
        title={muted ? "Unmute interviewer voice" : "Mute interviewer voice"}
      >
        {muted ? (
          <VolumeX className="h-4 w-4" />
        ) : (
          <Volume2 className="h-4 w-4" />
        )}
      </button>
      <button
        type="button"
        onClick={onToggleMic}
        className={cn(
          "grid h-9 w-9 place-items-center rounded-md transition-colors",
          micPaused
            ? "bg-muted text-muted-foreground hover:bg-muted/70"
            : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/20"
        )}
        title={micPaused ? "Resume microphone" : "Pause microphone"}
      >
        {micPaused ? (
          <MicOff className="h-4 w-4" />
        ) : (
          <Mic className="h-4 w-4" />
        )}
      </button>
    </div>
  );
}

function statusDot(status: LiveStatus, micPaused: boolean): string {
  if (micPaused) return "bg-muted-foreground/40";
  switch (status) {
    case "calibrating":
    case "connecting":
      return "bg-sky-500 animate-pulse";
    case "user_speaking":
      return "bg-red-500 animate-pulse";
    case "processing_audio":
    case "thinking":
    case "speaking":
      return "bg-amber-500 animate-pulse";
    case "ignored_audio":
      return "bg-zinc-500";
    case "ready":
      return "bg-emerald-500";
    case "error":
      return "bg-red-600";
    default:
      return "bg-muted-foreground/40";
  }
}

function statusBarTone(status: LiveStatus): string {
  switch (status) {
    case "calibrating":
      return "border-sky-500/30 bg-sky-500/5";
    case "user_speaking":
      return "border-red-500/30 bg-red-500/5";
    case "ignored_audio":
      return "border-zinc-500/30 bg-zinc-500/5";
    case "processing_audio":
    case "thinking":
      return "border-amber-500/30 bg-amber-500/5";
    default:
      return "bg-card";
  }
}

function ignoredHint(reason: string | null): string {
  switch (reason) {
    case "speaker_mismatch":
      return "Speaker did not match calibration.";
    case "too_short":
      return "Speech was too short to verify.";
    case "empty_transcript":
    case "transcription_failed":
      return "No usable transcript was detected.";
    case "low_transcript_confidence":
      return "Transcript confidence was too low.";
    case "speaker_verifier_error":
      return "Speaker verification failed closed.";
    default:
      return "Rejected before sending to the interviewer.";
  }
}
