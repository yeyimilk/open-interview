import { Loader2, Mic } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ClaimMappingOut,
  ProjectOut,
  ResumeOut,
  api,
} from "../../api/client";
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

type Mode = "resume" | "project";

export function InterviewerStartPage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const presetProject = params.get("project_id") || "";
  const presetResume = params.get("resume_id") || "";

  const [mode, setMode] = useState<Mode>(presetProject ? "project" : "resume");
  const [resumes, setResumes] = useState<ResumeOut[]>([]);
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [resumeId, setResumeId] = useState(presetResume);
  const [projectId, setProjectId] = useState(presetProject);
  const [position, setPosition] = useState("swe_generic");
  const [level, setLevel] = useState("mid");
  const [n, setN] = useState(5);
  const [busy, setBusy] = useState(false);
  const [mappings, setMappings] = useState<ClaimMappingOut[] | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [r, p] = await Promise.all([
          api.listResumes(),
          api.listProjects(),
        ]);
        setResumes(r);
        setProjects(p);
        if (!resumeId && r.length > 0) setResumeId(r[0].id);
        if (!projectId && p.length > 0) setProjectId(p[0].id);
      } catch (e) {
        toast.error("Failed to load options", {
          description: (e as Error).message,
        });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When the selected resume changes, fetch its claim mappings so we can
  // tell the user how many questions will be code-grounded.
  useEffect(() => {
    if (mode !== "resume" || !resumeId) {
      setMappings(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const m = await api.listClaimMappings(resumeId);
        if (!cancelled) setMappings(m);
      } catch {
        if (!cancelled) setMappings([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode, resumeId]);

  const groundedCount = useMemo(
    () => (mappings || []).filter((m) => m.project_id).length,
    [mappings]
  );
  const totalClaims = mappings?.length ?? 0;

  async function start() {
    if (mode === "resume" && !resumeId) {
      toast.error("Pick a resume first");
      return;
    }
    if (mode === "project" && !projectId) {
      toast.error("Pick a project first");
      return;
    }
    setBusy(true);
    try {
      const s = await api.createInterviewerSession(
        mode === "resume"
          ? { resume_id: resumeId, position, level, n_questions: n }
          : { project_id: projectId, position, level, n_questions: n }
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
        description="Pick a resume to drive the questions. Claims grounded in your projects get code-referenced questions."
      />
      <Card className="max-w-2xl">
        <CardHeader>
          <CardTitle>Setup</CardTitle>
          <CardDescription>
            Resume-driven by default. Switch to a single project if you want
            questions tightly scoped to one repo.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2 text-sm">
            <button
              type="button"
              onClick={() => setMode("resume")}
              className={
                "px-3 py-1 rounded-md border transition " +
                (mode === "resume"
                  ? "bg-primary text-primary-foreground border-primary"
                  : "hover:bg-muted")
              }
            >
              From resume
            </button>
            <button
              type="button"
              onClick={() => setMode("project")}
              className={
                "px-3 py-1 rounded-md border transition " +
                (mode === "project"
                  ? "bg-primary text-primary-foreground border-primary"
                  : "hover:bg-muted")
              }
            >
              From a project
            </button>
          </div>

          {mode === "resume" ? (
            <div className="space-y-2">
              <Label>Resume</Label>
              <Select value={resumeId} onValueChange={setResumeId}>
                <SelectTrigger>
                  <SelectValue placeholder="Pick a resume" />
                </SelectTrigger>
                <SelectContent>
                  {resumes.map((r) => (
                    <SelectItem key={r.id} value={r.id}>
                      {r.original_filename}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {resumes.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Upload a resume first to use this mode.
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Questions cover your experience, listed skills, system
                  design, and (for senior+) architecture and algorithms.
                  {mappings && groundedCount > 0
                    ? ` ${groundedCount} of ${totalClaims} resume claims are grounded in your projects — those questions cite your code.`
                    : null}
                </p>
              )}
            </div>
          ) : (
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
                      <span className="text-muted-foreground">
                        ({p.status})
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

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
