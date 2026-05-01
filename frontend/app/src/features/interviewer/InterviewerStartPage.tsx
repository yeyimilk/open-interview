import { Loader2, Mic } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ProjectOut, api } from "../../api/client";
import { PageHeader } from "../../components/common/PageHeader";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";

const LEVELS = [
  { value: "junior", label: "Junior" },
  { value: "mid", label: "Mid" },
  { value: "senior", label: "Senior" },
  { value: "tech_lead", label: "Tech Lead" },
];

export function InterviewerStartPage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const presetProject = params.get("project_id") || "";
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [projectId, setProjectId] = useState(presetProject);
  const [position, setPosition] = useState("swe_generic");
  const [level, setLevel] = useState("mid");
  const [n, setN] = useState(5);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const p = await api.listProjects();
        setProjects(p);
        if (!projectId && p.length > 0) setProjectId(p[0].id);
      } catch (e) {
        toast.error("Failed to load projects", {
          description: (e as Error).message,
        });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function start() {
    if (!projectId) {
      toast.error("Pick a project first");
      return;
    }
    setBusy(true);
    try {
      const s = await api.createInterviewerSession(
        projectId,
        position,
        level,
        n
      );
      nav(`/interviewer/${s.id}`);
    } catch (e) {
      toast.error("Failed to start", {
        description: (e as Error).message,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="New mock interview"
        description="Pick a project, target role, and level. Your first question is auto-generated."
      />
      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Setup</CardTitle>
          <CardDescription>
            If no QA set exists yet for this combination, one is generated in
            the background and used live.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Project</Label>
            <Select value={projectId} onValueChange={setProjectId}>
              <SelectTrigger>
                <SelectValue placeholder="Pick a project" />
              </SelectTrigger>
              <SelectContent>
                {projects.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}{" "}
                    <span className="text-muted-foreground">({p.status})</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Position</Label>
              <Select value={position} onValueChange={setPosition}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="swe_generic">SWE (generic)</SelectItem>
                  <SelectItem value="applied_ai">Applied AI</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Level</Label>
              <Select value={level} onValueChange={setLevel}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LEVELS.map((l) => (
                    <SelectItem key={l.value} value={l.value}>
                      {l.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="n">Number of questions</Label>
            <Input
              id="n"
              type="number"
              min={1}
              max={20}
              value={n}
              onChange={(e) => setN(parseInt(e.target.value || "5", 10))}
              className="w-28"
            />
          </div>
          <Button onClick={start} disabled={busy} className="w-full sm:w-auto">
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Starting...
              </>
            ) : (
              <>
                <Mic className="h-4 w-4" /> Start interview
              </>
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
