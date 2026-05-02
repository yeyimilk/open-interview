import { ArrowLeft, BrainCircuit } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ChatMessageOut, ChatSessionOut, api } from "../../api/client";
import { EditableTitle } from "../../components/common/EditableTitle";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { StreamingChat } from "./StreamingChat";

export function ChatSessionPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [session, setSession] = useState<ChatSessionOut | null>(null);
  const [messages, setMessages] = useState<ChatMessageOut[] | null>(null);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      try {
        const ms = await api.listGeneralMessages(id);
        setMessages(ms);
        const all = await api.listGeneralSessions();
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
      const s = await api.endGeneralSession(id);
      setSession(s);
      toast.success("Chat ended", {
        description: "Memory has been distilled and saved.",
      });
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    }
  }

  async function rename(next: string) {
    const updated = await api.renameGeneralSession(id, next || null);
    setSession(updated);
  }

  async function refreshSession() {
    // After the first user message the server may have auto-titled the
    // session — re-fetch so the header reflects it.
    try {
      const all = await api.listGeneralSessions();
      const fresh = all.find((s) => s.id === id);
      if (fresh) setSession(fresh);
    } catch {
      // Non-fatal; the title will refresh on the next page load.
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
        title={
          <EditableTitle
            value={session?.title ?? null}
            onSave={rename}
            placeholder="Untitled chat"
            readOnly={!session || session.status === "ended"}
          />
        }
        description="Workspace-aware general assistant. Same agent that powers WhatsApp /chat."
        actions={
          <>
            {session ? <StatusPill status={session.status} /> : null}
            <Button variant="outline" onClick={() => nav("/chat")}>
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
            endpoint={`/general/sessions/${id}/messages`}
            placeholder="Ask anything — projects, resumes, debugging, brainstorms..."
            onAfterSend={refreshSession}
          />
        </CardContent>
      </Card>
    </div>
  );
}
