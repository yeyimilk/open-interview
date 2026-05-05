import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../api/client";
import { ClientFrame, ServerFrame } from "./protocol";
import { CaptureHandle, startCapture } from "./Recorder";
import { Speaker } from "./Speaker";
import { Vad } from "./vad";

export type LiveStatus =
  | "idle"
  | "connecting"
  | "ready" // connected, mic on, no speech detected
  | "user_speaking" // VAD says user is currently speaking
  | "thinking" // we've committed; STT + LLM in flight
  | "speaking" // assistant audio is playing
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
  micLevel: number;
  currentTurn: LiveTurnUI | null;
  /** Turns whose assistant reply has finished but for which the parent
   *  hasn't yet refreshed `initialMessages` — render them so the bubble
   *  doesn't blink. Call `dropPersisted` once `initialMessages` includes
   *  the corresponding rows. */
  completedTurns: LiveTurnUI[];
  dropPersisted: (persistedAssistantContents: string[]) => void;
  muted: boolean;
  micPaused: boolean;
  setMuted: (m: boolean) => void;
  setMicPaused: (p: boolean) => void;
  bargeIn: () => void;
  disconnect: () => void;
}

const MIN_TURN_AUDIO_MS = 250;

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
  const [micLevel, setMicLevel] = useState(0);
  const [currentTurn, setCurrentTurn] = useState<LiveTurnUI | null>(null);
  const [completedTurns, setCompletedTurns] = useState<LiveTurnUI[]>([]);
  const [muted, setMutedState] = useState(false);
  const [micPaused, setMicPausedState] = useState(false);
  const micPausedRef = useRef(false);

  const dropPersisted = useCallback((persistedAssistantContents: string[]) => {
    if (persistedAssistantContents.length === 0) return;
    setCompletedTurns((prev) => {
      if (prev.length === 0) return prev;
      const persisted = new Set(persistedAssistantContents);
      const next = prev.filter((t) => !persisted.has(t.assistantText));
      return next.length === prev.length ? prev : next;
    });
  }, []);

  const wsRef = useRef<WebSocket | null>(null);
  const captureRef = useRef<CaptureHandle | null>(null);
  const turnRef = useRef<LiveTurnUI | null>(null);
  const speakerRef = useRef<Speaker | null>(null);
  if (speakerRef.current === null) speakerRef.current = new Speaker();
  const vadRef = useRef<Vad | null>(null);
  const speechStartAtRef = useRef<number>(0);
  const utteranceActiveRef = useRef(false);

  const send = useCallback((frame: ClientFrame) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(frame));
  }, []);

  const setMuted = useCallback((m: boolean) => {
    setMutedState(m);
    speakerRef.current?.setMuted(m);
  }, []);

  const setMicPaused = useCallback(
    (p: boolean) => {
      micPausedRef.current = p;
      setMicPausedState(p);
      if (p) {
        // Discard any in-progress utterance.
        const cap = captureRef.current;
        if (cap && utteranceActiveRef.current) {
          cap.endUtterance().catch(() => {});
          utteranceActiveRef.current = false;
        }
        send({ type: "mic_pause" });
        if (statusRef.current === "user_speaking") setStatusBoth("ready");
      } else {
        send({ type: "mic_resume" });
      }
    },
    [send, setStatusBoth]
  );

  const bargeIn = useCallback(() => {
    speakerRef.current?.cancel();
    send({ type: "barge_in" });
  }, [send]);

  const cleanup = useCallback(() => {
    captureRef.current?.stop();
    captureRef.current = null;
    speakerRef.current?.cancel();
    setMicLevel(0);
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
  }, []);

  const disconnect = useCallback(() => {
    cleanup();
    setStatusBoth("closed");
  }, [cleanup, setStatusBoth]);

  function handleServerFrame(frame: ServerFrame) {
    switch (frame.type) {
      case "ready":
        if (statusRef.current === "connecting") setStatusBoth("ready");
        break;
      case "final_transcript": {
        const next: LiveTurnUI = {
          userTranscript: frame.text,
          assistantText: "",
          voice: (frame as any).voice,
          pending: true,
        };
        turnRef.current = next;
        setCurrentTurn({ ...next });
        if (statusRef.current !== "user_speaking") setStatusBoth("thinking");
        break;
      }
      case "assistant_token": {
        const t = turnRef.current;
        if (!t) return;
        t.assistantText += frame.text;
        setCurrentTurn({ ...t });
        speakerRef.current?.push(frame.text);
        // While the assistant is talking, the room is louder and TTS may
        // leak via speakers — raise the VAD bar so casual sounds (typing,
        // a sigh) don't trigger barge-in.
        vadRef.current?.setSpeakingMode(true);
        if (statusRef.current === "thinking") setStatusBoth("speaking");
        break;
      }
      case "assistant_done": {
        const t = turnRef.current;
        if (t) {
          const finished: LiveTurnUI = { ...t, pending: false };
          // Push into the completed buffer so the bubble keeps showing
          // while the parent's `reload()` is in flight.
          setCompletedTurns((prev) => [...prev, finished]);
        }
        speakerRef.current?.flush();
        turnRef.current = null;
        setCurrentTurn(null);
        // Keep speaking-mode VAD on while TTS is still draining — the
        // Speaker's `isPlaying()` is the real gate during that window.
        setTimeout(() => vadRef.current?.setSpeakingMode(false), 1200);
        if (statusRef.current !== "user_speaking") setStatusBoth("ready");
        onTurnDone?.();
        break;
      }
      case "error":
        // eslint-disable-next-line no-console
        console.warn("live error:", frame.message);
        speakerRef.current?.cancel();
        vadRef.current?.setSpeakingMode(false);
        if (
          statusRef.current === "thinking" ||
          statusRef.current === "speaking"
        )
          setStatusBoth("ready");
        break;
    }
  }

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setStatusBoth("connecting");
    setError(null);

    const vad = new Vad({
      onSpeechStart: () => {
        if (micPausedRef.current) return;
        // While the assistant's TTS is playing, the mic almost certainly
        // hears the speaker output (browser AEC can't see speechSynthesis
        // as a reference). Ignore this trigger entirely.
        if (speakerRef.current?.isPlaying()) return;
        speechStartAtRef.current = performance.now();
        send({ type: "voice_start" });
        const cap = captureRef.current;
        if (cap && !utteranceActiveRef.current) {
          cap.startUtterance();
          utteranceActiveRef.current = true;
        }
        setStatusBoth("user_speaking");
      },
      onSpeechEnd: () => {
        if (micPausedRef.current) return;
        const dur = performance.now() - speechStartAtRef.current;
        const cap = captureRef.current;
        const ws = wsRef.current;
        if (!cap || !utteranceActiveRef.current) return;
        utteranceActiveRef.current = false;
        cap
          .endUtterance()
          .then((blob) => {
            if (!blob || dur < MIN_TURN_AUDIO_MS) {
              if (statusRef.current === "user_speaking") setStatusBoth("ready");
              return;
            }
            return blob.arrayBuffer().then((buf) => {
              if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(buf);
                send({ type: "end_user_turn" });
                setStatusBoth("thinking");
              }
            });
          })
          .catch(() => {
            if (statusRef.current === "user_speaking") setStatusBoth("ready");
          });
      },
    });
    vadRef.current = vad;

    (async () => {
      try {
        const t = await api.getRealtimeTicket(sessionId);
        if (cancelled) return;
        const ws = new WebSocket(t.ws_url);
        wsRef.current = ws;
        ws.binaryType = "arraybuffer";
        ws.onopen = () =>
          ws.send(JSON.stringify({ type: "hello", ticket: t.ticket }));
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

        const cap = await startCapture({
          onLevel: (rms, nowMs) => {
            setMicLevel(Math.min(1, rms * 4));
            if (micPausedRef.current) return;
            // Hard gate while TTS is playing: keep the analyser running
            // (so the mic level still updates) but never feed those
            // samples into VAD. This prevents the AI-talks-to-itself
            // loop on devices without strong echo cancellation.
            if (speakerRef.current?.isPlaying()) return;
            vad.feed(rms, nowMs);
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
        send({ type: "config", mime: cap.mime });
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
