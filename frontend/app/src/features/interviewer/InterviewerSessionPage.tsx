import { ArrowLeft, Clock4, Flag, Mic, Radio, Type } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ChatMessageOut,
  ChatSessionOut,
  api,
} from "../../api/client";
import { AudioStreamingChat } from "../chat/AudioStreamingChat";
import { LiveAudioChat } from "../chat/live/LiveAudioChat";
import { EditableTitle } from "../../components/common/EditableTitle";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Progress } from "../../components/ui/progress";
import { Skeleton } from "../../components/ui/skeleton";
import { cn } from "../../lib/cn";
import { StreamingChat } from "../chat/StreamingChat";

export function InterviewerSessionPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [session, setSession] = useState<ChatSessionOut | null>(null);
  const [messages, setMessages] = useState<ChatMessageOut[] | null>(null);
  const [ending, setEnding] = useState(false);
  const [mode, setMode] = useState<"text" | "audio" | "live">("text");
  const messagesRef = useRef<ChatMessageOut[] | null>(null);
  messagesRef.current = messages;

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: any = null;
    async function load() {
      try {
        const ms = await api.listInterviewerMessages(id);
        const all = await api.listInterviewerSessions();
        if (cancelled) return;
        setMessages(ms);
        setSession(all.find((s) => s.id === id) || null);
      } catch (e) {
        if (!cancelled) {
          toast.error("Failed to load", {
            description: (e as Error).message,
          });
        }
      }
    }
    void load();
    let polls = 0;
    timer = setInterval(() => {
      polls += 1;
      const cur = messagesRef.current;
      if (polls > 20 || (cur && cur.length > 0)) {
        clearInterval(timer);
        return;
      }
      void load();
    }, 4000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [id]);

  async function endSession() {
    setEnding(true);
    try {
      await api.endInterviewerSession(id);
      nav(`/interviewer/${id}/evaluation`);
    } catch (e) {
      toast.error("End failed", { description: (e as Error).message });
    } finally {
      setEnding(false);
    }
  }

  async function reload() {
    try {
      setMessages(await api.listInterviewerMessages(id));
      const all = await api.listInterviewerSessions();
      setSession(all.find((s) => s.id === id) || null);
    } catch {
      /* noop */
    }
  }

  async function rename(next: string) {
    const updated = await api.renameInterviewerSession(id, next || null);
    setSession(updated);
  }

  if (messages === null) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-1/3" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  const target = (session?.target || {}) as any;
  const latestAction = latestAssistantAction(messages);
  const askedCount = (target.asked_ids || []).length;
  const planned: number = target.n_questions || 0;
  const progress = planned > 0 ? Math.min(100, (askedCount / planned) * 100) : 0;

  return (
    <div>
      <PageHeader
        title={
          <EditableTitle
            value={session?.title ?? null}
            onSave={rename}
            placeholder="Mock interview"
            readOnly={!session || session.status === "ended"}
          />
        }
        description={
          <span className="flex items-center gap-3 flex-wrap">
            <span className="capitalize">
              {target.position?.replace("_", " ")}
            </span>
            <span className="text-muted-foreground">·</span>
            <span className="capitalize">
              {target.level?.replace("_", " ")}
            </span>
            {target.scope === "resume" && target.resume_filename ? (
              <>
                <span className="text-muted-foreground">·</span>
                <span title="Resume-driven session">
                  resume: {target.resume_filename}
                </span>
              </>
            ) : null}
            <span className="text-muted-foreground">·</span>
            <span className="inline-flex items-center gap-1">
              <Clock4 className="h-3.5 w-3.5" />
              {askedCount}
              {planned ? ` / ${planned}` : ""} asked
            </span>
          </span>
        }
        actions={
          <>
            {session ? <StatusPill status={session.status} /> : null}
            <Button variant="outline" onClick={() => nav("/interviewer")}>
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
            <Button
              variant="destructive"
              onClick={endSession}
              disabled={ending || session?.status === "ended"}
            >
              <Flag className="h-4 w-4" />
              {ending ? "Evaluating..." : "End & evaluate"}
            </Button>
          </>
        }
      />

      {planned > 0 && (
        <div className="mb-4">
          <Progress value={progress} />
        </div>
      )}
      {latestAction ? (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Badge variant="outline">{latestAction.replace(/_/g, " ")}</Badge>
          <span className="text-xs text-muted-foreground">
            Interviewer is tracking whether this turn deepens the current topic or starts a new one.
          </span>
        </div>
      ) : null}

      <div className="grid gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-muted-foreground">
              Answer mode:
            </span>
            <div className="inline-flex rounded-md border bg-muted/40 p-0.5">
              <button
                type="button"
                onClick={() => setMode("text")}
                className={cn(
                  "px-2.5 py-1 rounded text-xs inline-flex items-center gap-1",
                  mode === "text"
                    ? "bg-background shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Type className="h-3.5 w-3.5" /> Text
              </button>
              <button
                type="button"
                onClick={() => setMode("audio")}
                className={cn(
                  "px-2.5 py-1 rounded text-xs inline-flex items-center gap-1",
                  mode === "audio"
                    ? "bg-background shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
                title="Speak your answer; we'll analyse pace, fillers, and confidence."
              >
                <Mic className="h-3.5 w-3.5" /> Voice
              </button>
              <button
                type="button"
                onClick={() => setMode("live")}
                className={cn(
                  "px-2.5 py-1 rounded text-xs inline-flex items-center gap-1",
                  mode === "live"
                    ? "bg-background shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                )}
                title="Continuous live audio chat over WebSocket."
              >
                <Radio className="h-3.5 w-3.5" /> Live
              </button>
            </div>
            {mode === "audio" ? (
              <span className="text-xs text-muted-foreground">
                Tip: speak naturally — we score pace, fillers, and confidence.
              </span>
            ) : mode === "live" ? (
              <span className="text-xs text-muted-foreground">
                Live mode: a streaming WebSocket conversation; turns are still
                transcribed and saved.
              </span>
            ) : null}
          </div>
          <Card>
            <CardContent className="p-3 md:p-4">
              {mode === "text" ? (
                <StreamingChat
                  initialMessages={messages}
                  endpoint={`/interviewer/sessions/${id}/messages`}
                  placeholder="Type your answer here..."
                  onAfterSend={reload}
                />
              ) : mode === "audio" ? (
                <AudioStreamingChat
                  initialMessages={messages}
                  endpoint={`/interviewer/sessions/${id}/messages/audio`}
                  disabled={session?.status === "ended"}
                  onAfterSend={reload}
                />
              ) : (
                <LiveAudioChat
                  sessionId={id}
                  initialMessages={messages}
                  disabled={session?.status === "ended"}
                  onAfterTurn={reload}
                />
              )}
            </CardContent>
          </Card>
        </div>

      </div>
    </div>
  );
}

export function latestAssistantAction(messages: ChatMessageOut[]): string | null {
  for (const msg of [...messages].reverse()) {
    if (msg.role !== "assistant" || !msg.meta) continue;
    const action = msg.meta.next_action || msg.meta.thread_state?.last_action;
    if (typeof action === "string" && action) return action;
  }
  return null;
}
