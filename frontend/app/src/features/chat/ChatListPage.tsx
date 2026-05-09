import { ArrowRight, Loader2, MessageSquare, Plus, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ChatSessionOut, api } from "../../api/client";
import { EmptyState } from "../../components/common/EmptyState";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";

export function ChatListPage() {
  const nav = useNavigate();
  const [sessions, setSessions] = useState<ChatSessionOut[]>([]);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        setSessions(await api.listGeneralSessions());
      } catch (e) {
        toast.error("Failed to load", {
          description: (e as Error).message,
        });
      }
    })();
  }, []);

  async function start() {
    setBusy(true);
    try {
      const s = await api.createGeneralSession(title || null);
      nav(`/chat/${s.id}`);
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Chat"
        description="General-purpose assistant with access to your projects, resumes, and memory. Same agent that powers WhatsApp /chat."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/history">
                <Search className="h-4 w-4" /> Search history
              </Link>
            </Button>
            <Dialog open={open} onOpenChange={setOpen}>
              <DialogTrigger asChild>
                <Button>
                  <Plus className="h-4 w-4" /> New chat
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Start a chat</DialogTitle>
                  <DialogDescription>
                    Workspace-aware general chat. Ask anything; the assistant
                    knows what projects and resumes you have on file.
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="c-title">Title (optional)</Label>
                    <Input
                      id="c-title"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="e.g. Brainstorm side projects, debug a stack trace..."
                    />
                  </div>
                </div>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button type="button" onClick={start} disabled={busy}>
                    {busy ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" /> Creating...
                      </>
                    ) : (
                      "Start chat"
                    )}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </>
        }
      />

      <Card>
        <CardContent className="p-0">
          {sessions.length === 0 ? (
            <EmptyState
              icon={MessageSquare}
              title="No chats yet"
              description="Start a chat to ask anything — workspace-aware general assistant."
              action={
                <Button onClick={() => setOpen(true)}>
                  <Plus className="h-4 w-4" /> New chat
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Turns</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead className="text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">
                      {s.title || (
                        <span className="text-muted-foreground italic">
                          Untitled
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <StatusPill status={s.status} />
                    </TableCell>
                    <TableCell>{s.turn_count}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(s.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button asChild size="sm" variant="ghost">
                        <Link to={`/chat/${s.id}`}>
                          Open <ArrowRight className="h-4 w-4" />
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
