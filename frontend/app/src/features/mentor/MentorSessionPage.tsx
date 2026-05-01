import { ArrowLeft, BrainCircuit } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ChatMessageOut, ChatSessionOut, api } from "../../api/client";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { StreamingChat } from "../chat/StreamingChat";

export function MentorSessionPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [session, setSession] = useState<ChatSessionOut | null>(null);
  const [messages, setMessages] = useState<ChatMessageOut[] | null>(null);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      try {
        const ms = await api.listMentorMessages(id);
        setMessages(ms);
        const all = await api.listMentorSessions();
        setSession(all.find((s) => s.id === id) || null);
      } catch (e) {
        toast.error("Failed to load", {
          description: (e as Error).message,
        });
      }
    })();
  }, [id]);

  async function endSession() {
    try {
      const s = await api.endMentorSession(id);
      setSession(s);
      toast.success("Session ended", {
        description: "Memory has been distilled and saved.",
      });
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    }
  }

  if (messages === null) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-1/3" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={session?.title || "Mentor session"}
        description="Your AI mentor remembers context across sessions."
        actions={
          <>
            {session ? <StatusPill status={session.status} /> : null}
            <Button variant="outline" onClick={() => nav("/mentor")}>
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
            <Button
              variant="outline"
              onClick={endSession}
              disabled={session?.status === "ended"}
            >
              <BrainCircuit className="h-4 w-4" /> End & distill memory
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="p-3 md:p-4">
          <StreamingChat
            initialMessages={messages}
            endpoint={`/mentor/sessions/${id}/messages`}
            placeholder="Ask anything about your project, design, or interviews..."
          />
        </CardContent>
      </Card>
    </div>
  );
}
