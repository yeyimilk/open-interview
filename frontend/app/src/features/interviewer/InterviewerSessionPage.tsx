import { ArrowLeft, CheckCircle2, Clock4, Flag } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ChatMessageOut,
  ChatSessionOut,
  api,
} from "../../api/client";
import { EditableTitle } from "../../components/common/EditableTitle";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Progress } from "../../components/ui/progress";
import { Skeleton } from "../../components/ui/skeleton";
import { StreamingChat } from "../chat/StreamingChat";

export function InterviewerSessionPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [session, setSession] = useState<ChatSessionOut | null>(null);
  const [messages, setMessages] = useState<ChatMessageOut[] | null>(null);
  const [ending, setEnding] = useState(false);
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
  const currentQuestion: string = target.current_question || "";
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

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <CardContent className="p-3 md:p-4">
              <StreamingChat
                initialMessages={messages}
                endpoint={`/interviewer/sessions/${id}/messages`}
                placeholder="Type your answer here..."
                onAfterSend={reload}
              />
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          {currentQuestion ? (
            <Card className="border-primary/30 bg-primary/5">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <CheckCircle2 className="h-4 w-4 text-primary" /> Current
                  question
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm whitespace-pre-wrap leading-relaxed">
                  {currentQuestion}
                </p>
              </CardContent>
            </Card>
          ) : messages.length === 0 ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Preparing your interview...
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                Generating questions for this project and level. The first
                question will appear automatically.
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">How this works</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground space-y-2">
              <p>
                Answer in the chat. The interviewer will evaluate, give
                feedback, then move to the next question.
              </p>
              <p>
                When you're done, hit{" "}
                <Badge variant="muted">End & evaluate</Badge> to get a full
                rubric.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
