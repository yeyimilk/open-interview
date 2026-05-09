import {
  ArrowLeft,
  Briefcase,
  Download,
  ExternalLink,
  FileText,
  IdCard,
  Link2,
  Loader2,
  Mic,
  Quote,
  RefreshCw,
  Sparkles,
  Trash2,
  Wrench,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ClaimMappingOut, ProjectOut, ResumeDetail, api } from "../../api/client";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "../../components/ui/accordion";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import { Skeleton } from "../../components/ui/skeleton";

export function ResumeDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [resume, setResume] = useState<ResumeDetail | null>(null);
  const [mappings, setMappings] = useState<ClaimMappingOut[]>([]);
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  async function load() {
    try {
      const [r, m, p] = await Promise.all([
        api.getResume(id),
        api.listClaimMappings(id),
        api.listProjects(),
      ]);
      setResume(r);
      setMappings(m);
      setProjects(p);
    } catch (e) {
      toast.error("Failed to load", { description: (e as Error).message });
    }
  }

  useEffect(() => {
    if (!id) return;
    void load();
    const t = setInterval(() => {
      if (!resume?.parsed) void load();
    }, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, resume?.parsed]);

  async function remove() {
    if (!confirm("Delete this resume? Claim grounding will be removed too."))
      return;
    try {
      await api.deleteResume(id);
      toast.success("Resume deleted");
      nav("/resumes");
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    }
  }

  async function openOriginal() {
    try {
      const { blob } = await api.fetchResumeFile(id, true);
      const url = URL.createObjectURL(blob);
      const win = window.open(url, "_blank", "noopener,noreferrer");
      if (!win) {
        toast.error("Pop-up blocked", {
          description: "Allow pop-ups for this site to open the file.",
        });
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error("Could not open file", { description: (e as Error).message });
    }
  }

  async function downloadOriginal() {
    try {
      const { blob, filename } = await api.fetchResumeFile(id, false);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error("Download failed", { description: (e as Error).message });
    }
  }

  async function refreshGrounding() {
    setRefreshing(true);
    try {
      await api.runResumeNow(
        id,
        projects.filter((project) => project.status === "ready").map((project) => project.id)
      );
      toast.success("Resume processing started", {
        description: "Claim grounding will refresh in the background.",
      });
      await load();
    } catch (e) {
      toast.error("Refresh failed", { description: (e as Error).message });
    } finally {
      setRefreshing(false);
    }
  }

  if (!resume) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-1/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const parsed = resume.parsed as
    | {
        name?: string;
        contacts?: Record<string, string>;
        skills?: string[];
        experience?: any[];
        projects?: any[];
        claims?: { text: string; section?: string }[];
      }
    | null;
  const ready = !!parsed;
  const projectNameById = Object.fromEntries(
    projects.map((project) => [project.id, project.name])
  );

  return (
    <div>
      <div className="mb-3">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/resumes">
            <ArrowLeft className="h-4 w-4" /> All resumes
          </Link>
        </Button>
      </div>

      <PageHeader
        title={resume.original_filename}
        description={`Uploaded ${new Date(resume.created_at).toLocaleString()}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {ready ? (
              <StatusPill status="ready" />
            ) : (
              <StatusPill status="running" />
            )}
            <Button asChild>
              <Link to={`/interviewer/start?resume_id=${id}`}>
                <Mic className="h-4 w-4" /> Start interview
              </Link>
            </Button>
            <Button variant="outline" onClick={openOriginal}>
              <ExternalLink className="h-4 w-4" /> Open file
            </Button>
            <Button variant="outline" onClick={downloadOriginal}>
              <Download className="h-4 w-4" /> Download
            </Button>
            <Button
              variant="outline"
              onClick={refreshGrounding}
              disabled={refreshing || projects.length === 0}
            >
              {refreshing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Refresh grounding
            </Button>
            <Button
              variant="ghost"
              className="text-destructive hover:text-destructive"
              onClick={remove}
            >
              <Trash2 className="h-4 w-4" /> Delete
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 md:grid-cols-3 items-start">
        <div className="md:col-span-2 space-y-4 min-w-0">
          {!parsed ? (
            <Card>
              <CardContent className="py-10">
                <div className="flex flex-col items-center gap-3 text-center text-muted-foreground">
                  <Loader2 className="h-6 w-6 animate-spin text-primary" />
                  <p className="text-sm">
                    Parsing your resume... this page auto-refreshes.
                  </p>
                </div>
              </CardContent>
            </Card>
          ) : (
            <>
              {(parsed.name ||
                (parsed.contacts &&
                  Object.keys(parsed.contacts).length > 0)) && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <IdCard className="h-4 w-4 text-primary" /> Identity
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {parsed.name ? (
                      <div className="text-lg font-semibold">{parsed.name}</div>
                    ) : null}
                    {parsed.contacts &&
                    Object.keys(parsed.contacts).length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(parsed.contacts).map(([k, v]) => (
                          <Badge key={k} variant="muted">
                            <span className="text-muted-foreground mr-1">
                              {k}:
                            </span>
                            {v}
                          </Badge>
                        ))}
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              )}

              {parsed.skills?.length ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Wrench className="h-4 w-4 text-primary" /> Skills (
                      {parsed.skills.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-1.5">
                      {parsed.skills.map((s) => (
                        <Badge key={s} variant="secondary">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ) : null}

              {parsed.experience?.length ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Briefcase className="h-4 w-4 text-primary" /> Experience
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ol className="relative space-y-5 border-l border-border pl-5">
                      {parsed.experience.map((e: any, i: number) => (
                        <li key={i} className="relative">
                          <span className="absolute -left-[27px] top-1 h-3 w-3 rounded-full bg-primary ring-4 ring-background" />
                          <div className="text-sm font-semibold">
                            {e.title || "—"}
                            {e.company ? (
                              <span className="text-muted-foreground font-normal">
                                {" "}
                                · {e.company}
                              </span>
                            ) : null}
                          </div>
                          {e.period ? (
                            <div className="text-xs text-muted-foreground mt-0.5">
                              {e.period}
                            </div>
                          ) : null}
                          {e.bullets?.length ? (
                            <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground space-y-0.5">
                              {e.bullets.map((b: string, j: number) => (
                                <li key={j}>{b}</li>
                              ))}
                            </ul>
                          ) : null}
                        </li>
                      ))}
                    </ol>
                  </CardContent>
                </Card>
              ) : null}

              {parsed.projects?.length ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Sparkles className="h-4 w-4 text-primary" /> Projects (
                      {parsed.projects.length})
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-3">
                      {parsed.projects.map((p: any, i: number) => (
                        <li
                          key={i}
                          className="rounded-lg border bg-muted/30 p-3 space-y-1"
                        >
                          <div className="text-sm font-semibold">{p.name}</div>
                          {p.summary ? (
                            <div className="text-sm text-muted-foreground">
                              {p.summary}
                            </div>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              ) : null}

              {parsed.claims?.length ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Quote className="h-4 w-4 text-primary" /> Claims (
                      {parsed.claims.length})
                    </CardTitle>
                    <CardDescription>
                      Extracted statements that the interviewer may probe.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2">
                      {parsed.claims.map((c, i) => (
                        <li
                          key={i}
                          className="rounded-md border-l-2 border-primary/40 bg-muted/30 px-3 py-2 text-sm"
                        >
                          {c.text}
                          {c.section ? (
                            <span className="ml-2 text-xs text-muted-foreground">
                              ({c.section})
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              ) : null}

              {resume.text ? (
                <Card>
                  <CardContent className="py-2">
                    <Accordion type="single" collapsible>
                      <AccordionItem value="raw" className="border-b-0">
                        <AccordionTrigger className="text-sm">
                          <span className="flex items-center gap-2 text-muted-foreground">
                            <FileText className="h-4 w-4" /> Original text
                          </span>
                        </AccordionTrigger>
                        <AccordionContent>
                          <pre className="overflow-x-auto rounded-lg bg-muted/50 p-3 text-xs leading-relaxed whitespace-pre-wrap font-mono">
                            {resume.text.slice(0, 8000)}
                            {resume.text.length > 8000 ? "\n..." : ""}
                          </pre>
                        </AccordionContent>
                      </AccordionItem>
                    </Accordion>
                  </CardContent>
                </Card>
              ) : null}
            </>
          )}
        </div>

        <div className="space-y-4 md:sticky md:top-4">
          <GroundingCard mappings={mappings} projectNameById={projectNameById} />
        </div>
      </div>
    </div>
  );
}

function GroundingCard({
  mappings,
  projectNameById,
}: {
  mappings: ClaimMappingOut[];
  projectNameById: Record<string, string>;
}) {
  const [category, setCategory] = useState("all");
  const [section, setSection] = useState("all");
  const categories = Array.from(new Set(mappings.map((m) => m.category).filter(Boolean) as string[]));
  const sections = Array.from(new Set(mappings.map((m) => m.section).filter(Boolean) as string[]));
  const sorted = [...mappings]
    .filter((m) => category === "all" || m.category === category)
    .filter((m) => section === "all" || m.section === section)
    .sort((a, b) => b.confidence - a.confidence);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Link2 className="h-4 w-4 text-primary" /> Grounding ({mappings.length})
        </CardTitle>
        <CardDescription>Claim ↔ project code matches.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-3 grid gap-2 sm:grid-cols-2">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {categories.map((value) => (
                <SelectItem key={value} value={value}>
                  {value.replace(/_/g, " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={section} onValueChange={setSection}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All sections</SelectItem>
              {sections.map((value) => (
                <SelectItem key={value} value={value}>
                  {value.replace(/_/g, " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground italic">
            No matches yet. Grounding runs in the background after upload.
          </p>
        ) : (
          <ul className="space-y-3">
            {sorted.map((m) => {
              const pct = Math.max(0, Math.min(1, m.confidence));
              const projectName =
                (m.project_id && projectNameById[m.project_id]) || null;
              return (
                <li key={m.id} className="space-y-1.5">
                  <div className="space-y-1">
                    <p className="text-sm leading-snug">{m.claim}</p>
                    {projectName ? (
                      <Link
                        to={`/projects/${m.project_id}`}
                        className="inline-flex max-w-full items-center gap-1 truncate text-xs font-medium text-primary hover:underline"
                      >
                        <Briefcase className="h-3 w-3 shrink-0" />
                        <span className="truncate">{projectName}</span>
                      </Link>
                    ) : null}
                    <div className="flex flex-wrap gap-1">
                      {m.category ? <Badge variant="outline">{m.category.replace(/_/g, " ")}</Badge> : null}
                      {m.section ? <Badge variant="muted">{m.section}</Badge> : null}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full bg-primary transition-all"
                        style={{ width: `${pct * 100}%` }}
                      />
                    </div>
                    <span className="text-xs tabular-nums text-muted-foreground w-9 text-right">
                      {(pct * 100).toFixed(0)}%
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
