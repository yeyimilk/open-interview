import { Loader2, Mic } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ClaimMappingOut,
  CompanyInterviewProfileOut,
  InterviewPreference,
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
  const [targetCompany, setTargetCompany] = useState("");
  const [includeCompanyStyle, setIncludeCompanyStyle] = useState(true);
  const [languages, setLanguages] = useState("");
  const [algoWeight, setAlgoWeight] = useState(1);
  const [systemWeight, setSystemWeight] = useState(1);
  const [aiWeight, setAiWeight] = useState(1);
  const [languageWeight, setLanguageWeight] = useState(0.5);
  const [profiles, setProfiles] = useState<CompanyInterviewProfileOut[]>([]);
  const [busy, setBusy] = useState(false);
  const [mappings, setMappings] = useState<ClaimMappingOut[] | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [r, p, pref, cps] = await Promise.all([
          api.listResumes(),
          api.listProjects(),
          api.getInterviewPreferences().catch(() => null),
          api.listCompanyProfiles().catch(() => []),
        ]);
        setResumes(r);
        setProjects(p);
        setProfiles(cps);
        if (pref) applyPreference(pref);
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
          ? {
              resume_id: resumeId,
              position,
              level,
              n_questions: n,
              target_company: targetCompany || undefined,
              preferences: buildPreferences(),
            }
          : {
              project_id: projectId,
              position,
              level,
              n_questions: n,
              target_company: targetCompany || undefined,
              preferences: buildPreferences(),
            }
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

  function buildPreferences() {
    return {
      category_weights: {
        algorithms: algoWeight,
        system_design: systemWeight,
        ai_design: aiWeight,
        applied_ai_specific: aiWeight,
        language: languageWeight,
      },
      languages: languages
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      include_company_style: includeCompanyStyle,
    };
  }

  function applyPreference(pref: InterviewPreference) {
    if (pref.target_company) setTargetCompany(pref.target_company);
    setIncludeCompanyStyle(pref.include_company_style ?? true);
    setLanguages((pref.languages || []).join(", "));
    const w = pref.category_weights || {};
    if (typeof w.algorithms === "number") setAlgoWeight(w.algorithms);
    if (typeof w.system_design === "number") setSystemWeight(w.system_design);
    if (typeof (w.ai_design ?? w.applied_ai_specific) === "number") {
      setAiWeight((w.ai_design ?? w.applied_ai_specific) as number);
    }
    if (typeof w.language === "number") setLanguageWeight(w.language);
  }

  async function savePreferences() {
    try {
      await api.putInterviewPreferences({
        target_company: targetCompany || null,
        ...buildPreferences(),
        interview_style: "realistic",
      });
      toast.success("Interview preferences saved");
    } catch (e) {
      toast.error("Failed to save", { description: (e as Error).message });
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

          <div className="grid gap-4 border-t pt-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Target company</Label>
              <Input
                list="company-profiles"
                placeholder="Optional, e.g. Meta"
                value={targetCompany}
                onChange={(e) => setTargetCompany(e.target.value)}
              />
              <datalist id="company-profiles">
                {profiles.map((p) => (
                  <option key={p.id} value={p.company} />
                ))}
              </datalist>
            </div>
            <div className="space-y-2">
              <Label>Language focus</Label>
              <Input
                placeholder="Python, Java, SQL"
                value={languages}
                onChange={(e) => setLanguages(e.target.value)}
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            <WeightInput label="Algorithms" value={algoWeight} onChange={setAlgoWeight} />
            <WeightInput label="System design" value={systemWeight} onChange={setSystemWeight} />
            <WeightInput label="AI design" value={aiWeight} onChange={setAiWeight} />
            <WeightInput label="Language" value={languageWeight} onChange={setLanguageWeight} />
          </div>

          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={includeCompanyStyle}
              onChange={(e) => setIncludeCompanyStyle(e.target.checked)}
            />
            Use company-style weighting when a profile exists.
          </label>

          <Button type="button" variant="outline" onClick={savePreferences}>
            Save as default preferences
          </Button>

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

function WeightInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <Input
        type="number"
        min={0}
        max={3}
        step={0.1}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value || "0"))}
      />
    </div>
  );
}
