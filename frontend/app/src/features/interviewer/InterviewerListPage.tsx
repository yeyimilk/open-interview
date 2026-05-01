import { ArrowRight, Mic, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ChatSessionOut, api } from "../../api/client";
import { EmptyState } from "../../components/common/EmptyState";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";

export function InterviewerListPage() {
  const [sessions, setSessions] = useState<ChatSessionOut[]>([]);

  useEffect(() => {
    void (async () => {
      try {
        setSessions(await api.listInterviewerSessions());
      } catch (e) {
        toast.error("Failed to load", {
          description: (e as Error).message,
        });
      }
    })();
  }, []);

  return (
    <div>
      <PageHeader
        title="Mock interviews"
        description="Live, evaluated interviews with a final rubric and suggested practice plan."
        actions={
          <Button asChild>
            <Link to="/interviewer/start">
              <Plus className="h-4 w-4" /> New interview
            </Link>
          </Button>
        }
      />
      <Card>
        <CardContent className="p-0">
          {sessions.length === 0 ? (
            <EmptyState
              icon={Mic}
              title="No interviews yet"
              description="Start your first mock interview to see it here."
              action={
                <Button asChild>
                  <Link to="/interviewer/start">
                    <Plus className="h-4 w-4" /> Start interview
                  </Link>
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
                    <TableCell className="text-right space-x-1">
                      <Button asChild size="sm" variant="ghost">
                        <Link to={`/interviewer/${s.id}`}>
                          {s.status === "ended" ? "View" : "Resume"}{" "}
                          <ArrowRight className="h-4 w-4" />
                        </Link>
                      </Button>
                      {s.status === "ended" ? (
                        <Button asChild size="sm" variant="outline">
                          <Link to={`/interviewer/${s.id}/evaluation`}>
                            Evaluation
                          </Link>
                        </Button>
                      ) : null}
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
