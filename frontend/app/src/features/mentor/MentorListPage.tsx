import { ArrowRight, GraduationCap, Loader2, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ChatSessionOut, ProjectOut, api } from "../../api/client";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";

export function MentorListPage() {
  const nav = useNavigate();
  const [sessions, setSessions] = useState<ChatSessionOut[]>([]);
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [open, setOpen] = useState(false);
  const [projectId, setProjectId] = useState<string>("__none__");
  const [title, setTitle] = useState<string>("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [s, p] = await Promise.all([
          api.listMentorSessions(),
          api.listProjects(),
        ]);
        setSessions(s);
        setProjects(p);
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
      const s = await api.createMentorSession(
        projectId === "__none__" ? null : projectId,
        title || null
      );
      nav(`/mentor/${s.id}`);
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Mentor"
        description="Open-ended coaching grounded in your projects, with persistent memory across sessions."
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" /> New session
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Start a mentor session</DialogTitle>
                <DialogDescription>
                  Optionally pin a project so context can be retrieved
                  automatically.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="m-project">Project</Label>
                  <Select value={projectId} onValueChange={setProjectId}>
                    <SelectTrigger id="m-project">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__">None (general)</SelectItem>
                      {projects.map((p) => (
                        <SelectItem key={p.id} value={p.id}>
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="m-title">Title (optional)</Label>
                  <Input
                    id="m-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g. Async cancellation, monorepo refactor..."
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
                    "Start session"
                  )}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      <Card>
        <CardContent className="p-0">
          {sessions.length === 0 ? (
            <EmptyState
              icon={GraduationCap}
              title="No mentor sessions yet"
              description="Create your first session to start chatting with your AI mentor."
              action={
                <Button onClick={() => setOpen(true)}>
                  <Plus className="h-4 w-4" /> New session
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
                        <Link to={`/mentor/${s.id}`}>
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
