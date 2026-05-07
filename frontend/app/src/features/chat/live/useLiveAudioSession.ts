import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../api/client";
import { ClientFrame, ServerFrame } from "./protocol";
import { CaptureHandle, startCapture } from "./Recorder";
import { Speaker } from "./Speaker";

export type LiveStatus =
  | "idle"
  | "connecting"
  | "calibrating"
  | "ready"
  | "user_speaking"
  | "processing_audio"
  | "ignored_audio"
  | "thinking"
  | "speaking"
  | "error"
  | "closed";

export interface LiveTurnUI {
  userTranscript: string;
  assistantText: string;
  voice?: any;
  pending: boolean;
}

export interface UseLiveAudioSessionOptions {
  sessionId: string;
  enabled: boolean;
  onTurnDone?: () => void;
}

export interface UseLiveAudioSessionResult {
  status: LiveStatus;
  error: string | null;
  ignoredReason: string | null;
  micLevel: number;
  currentTurn: LiveTurnUI | null;
  completedTurns: LiveTurnUI[];
  dropPersisted: (persistedAssistantContents: string[]) => void;
  muted: boolean;
  micPaused: boolean;
  setMuted: (m: boolean) => void;
  setMicPaused: (p: boolean) => void;
  bargeIn: () => void;
  disconnect: () => void;
}

export function useLiveAudioSession(
  opts: UseLiveAudioSessionOptions
): UseLiveAudioSessionResult {
  const { sessionId, enabled, onTurnDone } = opts;
  const [status, setStatus] = useState<LiveStatus>("idle");
  const statusRef = useRef<LiveStatus>("idle");
  const setStatusBoth = useCallback((s: LiveStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  const [error, setError] = useState<string | null>(null);
  const [ignoredReason, setIgnoredReason] = useState<string | null>(null);
  const [micLevel, setMicLevel] = useState(0);
  const [currentTurn, setCurrentTurn] = useState<LiveTurnUI | null>(null);
  const [completedTurns, setCompletedTurns] = useState<LiveTurnUI[]>([]);
  const [muted, setMutedState] = useState(false);
  const [micPaused, setMicPausedState] = useState(false);
  const micPausedRef = useRef(false);
  const calibratedRef = useRef(false);
  const calibrationTimerRef = useRef<number | null>(null);
  const ignoredTimerRef = useRef<number | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const captureRef = useRef<CaptureHandle | null>(null);
  const turnRef = useRef<LiveTurnUI | null>(null);
  const speakerRef = useRef<Speaker | null>(null);
  if (speakerRef.current === null) speakerRef.current = new Speaker();

  const send = useCallback((frame: ClientFrame) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(frame));
  }, []);

  const dropPersisted = useCallback((persistedAssistantContents: string[]) => {
    if (persistedAssistantContents.length === 0) return;
    setCompletedTurns((prev) => {
      if (prev.length === 0) return prev;
      const persisted = new Set(persistedAssistantContents);
      const next = prev.filter((t) => !persisted.has(t.assistantText));
      return next.length === prev.length ? prev : next;
    });
  }, []);

  const setMuted = useCallback((m: boolean) => {
    setMutedState(m);
    speakerRef.current?.setMuted(m);
  }, []);

  const setMicPaused = useCallback(
    (p: boolean) => {
      micPausedRef.current = p;
      setMicPausedState(p);
      send({ type: p ? "mic_pause" : "mic_resume" });
      if (p && calibratedRef.current && statusRef.current !== "closed") {
        setStatusBoth("ready");
      }
    },
    [send, setStatusBoth]
  );

  const bargeIn = useCallback(() => {
    speakerRef.current?.cancel();
    send({ type: "barge_in" });
    if (statusRef.current === "speaking") setStatusBoth("ready");
  }, [send, setStatusBoth]);

  const clearCalibrationTimer = useCallback(() => {
    if (calibrationTimerRef.current !== null) {
      window.clearTimeout(calibrationTimerRef.current);
      calibrationTimerRef.current = null;
    }
  }, []);

  const clearIgnoredTimer = useCallback(() => {
    if (ignoredTimerRef.current !== null) {
      window.clearTimeout(ignoredTimerRef.current);
      ignoredTimerRef.current = null;
    }
  }, []);

  const showIgnoredTurn = useCallback(
    (reason: string | undefined) => {
      clearIgnoredTimer();
      setIgnoredReason(reason || "rejected");
      setStatusBoth("ignored_audio");
      ignoredTimerRef.current = window.setTimeout(() => {
        ignoredTimerRef.current = null;
        setIgnoredReason(null);
        if (statusRef.current === "ignored_audio" && calibratedRef.current) {
          setStatusBoth("ready");
        }
      }, 1600);
    },
    [clearIgnoredTimer, setStatusBoth]
  );

  const startCalibration = useCallback(
    (durationMs: number) => {
      clearCalibrationTimer();
      clearIgnoredTimer();
      setIgnoredReason(null);
      calibratedRef.current = false;
      setStatusBoth("calibrating");
      send({ type: "calibration_start" });
      calibrationTimerRef.current = window.setTimeout(() => {
        calibrationTimerRef.current = null;
        send({ type: "calibration_commit" });
        setStatusBoth("connecting");
      }, Math.max(1000, durationMs || 3000));
    },
    [clearCalibrationTimer, clearIgnoredTimer, send, setStatusBoth]
  );

  const cleanup = useCallback(() => {
    clearCalibrationTimer();
    clearIgnoredTimer();
    captureRef.current?.stop();
    captureRef.current = null;
    speakerRef.current?.cancel();
    setMicLevel(0);
    setIgnoredReason(null);
    calibratedRef.current = false;
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "bye" }));
      } catch {
        /* ignore */
      }
      ws.close();
    }
  }, [clearCalibrationTimer, clearIgnoredTimer]);

  const disconnect = useCallback(() => {
    cleanup();
    setStatusBoth("closed");
  }, [cleanup, setStatusBoth]);

  function handleServerFrame(frame: ServerFrame) {
    switch (frame.type) {
      case "ready":
        if (calibratedRef.current && statusRef.current === "connecting") {
          setStatusBoth("ready");
        }
        break;
      case "calibration_required":
        startCalibration(frame.duration_ms);
        break;
      case "calibration_ready":
        clearCalibrationTimer();
        calibratedRef.current = true;
        setError(null);
        setIgnoredReason(null);
        setStatusBoth("ready");
        break;
      case "calibration_error":
        clearCalibrationTimer();
        calibratedRef.current = false;
        setError(frame.message);
        setStatusBoth(frame.retryable === false ? "error" : "calibrating");
        break;
      case "user_speech_started":
        if (
          calibratedRef.current &&
          !micPausedRef.current &&
          statusRef.current !== "closed" &&
          statusRef.current !== "error" &&
          statusRef.current !== "thinking" &&
          statusRef.current !== "speaking"
        ) {
          clearIgnoredTimer();
          setError(null);
          setIgnoredReason(null);
          setStatusBoth("user_speaking");
        }
        break;
      case "user_speech_stopped":
        if (statusRef.current === "user_speaking") {
          setStatusBoth("processing_audio");
        }
        break;
      case "turn_ignored":
        if (
          calibratedRef.current &&
          statusRef.current !== "closed" &&
          statusRef.current !== "error" &&
          statusRef.current !== "thinking" &&
          statusRef.current !== "speaking"
        ) {
          showIgnoredTurn(frame.reason);
        }
        break;
      case "final_transcript": {
        clearIgnoredTimer();
        setIgnoredReason(null);
        const next: LiveTurnUI = {
          userTranscript: frame.text,
          assistantText: "",
          voice: (frame as any).voice,
          pending: true,
        };
        turnRef.current = next;
        setCurrentTurn({ ...next });
        setStatusBoth("thinking");
        break;
      }
      case "assistant_token": {
        const t = turnRef.current;
        if (!t) return;
        t.assistantText += frame.text;
        setCurrentTurn({ ...t });
        speakerRef.current?.push(frame.text);
        if (statusRef.current === "thinking") setStatusBoth("speaking");
        break;
      }
      case "assistant_done": {
        const t = turnRef.current;
        if (t) {
          setCompletedTurns((prev) => [...prev, { ...t, pending: false }]);
        }
        speakerRef.current?.flush();
        turnRef.current = null;
        setCurrentTurn(null);
        if (statusRef.current !== "closed") setStatusBoth("ready");
        onTurnDone?.();
        break;
      }
      case "error":
        // eslint-disable-next-line no-console
        console.warn("live error:", frame.message);
        speakerRef.current?.cancel();
        clearIgnoredTimer();
        setError(frame.message);
        setIgnoredReason(null);
        setStatusBoth("error");
        break;
    }
  }

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setStatusBoth("connecting");
    setError(null);

    (async () => {
      try {
        const t = await api.getRealtimeTicket(sessionId);
        if (cancelled) return;

        const cap = await startCapture({
          onLevel: (rms) => setMicLevel(Math.min(1, rms * 4)),
          onAudio: (chunk) => {
            const ws = wsRef.current;
            if (!ws || ws.readyState !== WebSocket.OPEN) return;
            if (micPausedRef.current) return;
            if (speakerRef.current?.isPlaying()) return;
            ws.send(chunk);
          },
          onError: (e) => {
            setError(e.message);
            setStatusBoth("error");
          },
        });
        if (cancelled) {
          cap.stop();
          return;
        }
        captureRef.current = cap;

        const ws = new WebSocket(t.ws_url);
        wsRef.current = ws;
        ws.binaryType = "arraybuffer";
        ws.onopen = () => {
          ws.send(JSON.stringify({ type: "hello", ticket: t.ticket }));
          ws.send(
            JSON.stringify({
              type: "config",
              audio_format: cap.audioFormat,
              sample_rate: cap.sampleRate,
              channels: cap.channels,
            } satisfies ClientFrame)
          );
        };
        ws.onmessage = (ev) => {
          if (typeof ev.data !== "string") return;
          let frame: ServerFrame | null = null;
          try {
            frame = JSON.parse(ev.data);
          } catch {
            return;
          }
          if (frame) handleServerFrame(frame);
        };
        ws.onerror = () => {
          if (!cancelled) {
            setError("WebSocket error");
            setStatusBoth("error");
          }
        };
        ws.onclose = () => {
          if (!cancelled) setStatusBoth("closed");
        };
      } catch (e) {
        if (!cancelled) {
          setError((e as Error).message);
          setStatusBoth("error");
        }
      }
    })();

    return () => {
      cancelled = true;
      cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sessionId]);

  return {
    status,
    error,
    ignoredReason,
    micLevel,
    currentTurn,
    completedTurns,
    dropPersisted,
    muted,
    micPaused,
    setMuted,
    setMicPaused,
    bargeIn,
    disconnect,
  };
}
