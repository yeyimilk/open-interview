import { ArrowRight, Mic, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ProjectDetail,
  ProjectDiagramOut,
  ProjectFileOut,
  QASetOut,
  api,
} from "../../api/client";
import { EmptyState } from "../../components/common/EmptyState";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import { Skeleton } from "../../components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../../components/ui/tabs";

const ALL_LEVELS = ["junior", "mid", "senior", "tech_lead"];

export function ProjectDetailPage() {
  const { id = "" } = useParams();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [files, setFiles] = useState<ProjectFileOut[]>([]);
  const [diagrams, setDiagrams] = useState<ProjectDiagramOut[]>([]);
  const [qaSets, setQaSets] = useState<QASetOut[]>([]);
  const [position, setPosition] = useState("swe_generic");
  const [levels, setLevels] = useState<Record<string, boolean>>({
    junior: true,
    mid: true,
    senior: true,
    tech_lead: true,
  });

  async function loadAll() {
    try {
      const [p, fs, ds, qs] = await Promise.all([
        api.getProject(id),
        api.listProjectFiles(id),
        api.listProjectDiagrams(id),
        api.listQASets(id),
      ]);
      setProject(p);
      setFiles(fs);
      setDiagrams(ds);
      setQaSets(qs);
    } catch (e) {
      toast.error("Failed to load project", {
        description: (e as Error).message,
      });
    }
  }

  async function generateQA() {
    try {
      const selected = ALL_LEVELS.filter((l) => levels[l]);
      if (selected.length === 0) return;
      await api.generateQA(id, position, selected);
      toast.success("QA generation queued", {
        description: `${selected.length} level(s) for ${position}`,
      });
      await loadAll();
    } catch (e) {
      toast.error("Generation failed", { description: (e as Error).message });
    }
  }

  useEffect(() => {
    if (!id) return;
    void loadAll();
    const t = setInterval(() => {
      if (!project || project.status !== "ready") void loadAll();
    }, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, project?.status]);

  if (!project) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-1/3" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const arch = project.architecture as
    | {
        summary?: string;
        components?: { name: string; role: string; deps?: string[] }[];
      }
    | null;
  const decisions =
    (project.interesting_decisions as
      | { title: string; detail: string; refs?: string[] }[]
      | null) || [];

  return (
    <div>
      <PageHeader
        title={project.name}
        description={`Created ${new Date(project.created_at).toLocaleString()}`}
        actions={
          <>
            <StatusPill status={project.status} />
            <Button asChild>
              <Link to={`/interviewer/start?project_id=${id}`}>
                <Mic className="h-4 w-4" /> Start mock interview
              </Link>
            </Button>
          </>
        }
      />

      {project.status !== "ready" && (
        <Card className="mb-6 border-primary/30 bg-primary/5">
          <CardHeader>
            <CardTitle>Ingestion in progress</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              We're chunking, embedding, summarizing, and drafting diagrams.
              This page refreshes automatically.
            </p>
            <Progress value={project.status === "ready" ? 100 : 50} />
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="qa">
            Interview QA
            {qaSets.length > 0 ? (
              <Badge variant="muted" className="ml-2">
                {qaSets.length}
              </Badge>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="diagrams">
            Diagrams
            {diagrams.length > 0 ? (
              <Badge variant="muted" className="ml-2">
                {diagrams.length}
              </Badge>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="files">
            Files
            {files.length > 0 ? (
              <Badge variant="muted" className="ml-2">
                {files.length}
              </Badge>
            ) : null}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Architecture summary</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="text-sm whitespace-pre-wrap">
                {arch?.summary ||
                  project.summary || (
                    <span className="text-muted-foreground italic">
                      Not yet generated.
                    </span>
                  )}
              </div>
              {arch?.components?.length ? (
                <div className="space-y-2">
                  <h4 className="text-sm font-medium">Components</h4>
                  <ul className="space-y-1.5 text-sm">
                    {arch.components.map((c) => (
                      <li key={c.name} className="flex flex-wrap gap-1.5 items-baseline">
                        <Badge variant="secondary" className="font-mono">
                          {c.name}
                        </Badge>
                        <span className="text-muted-foreground">{c.role}</span>
                        {c.deps?.length ? (
                          <span className="text-xs text-muted-foreground/80">
                            deps: {c.deps.join(", ")}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Interesting decisions ({decisions.length})</CardTitle>
            </CardHeader>
            <CardContent>
              {decisions.length === 0 ? (
                <p className="text-sm text-muted-foreground italic">
                  None yet.
                </p>
              ) : (
                <ul className="space-y-3 text-sm">
                  {decisions.map((d, i) => (
                    <li key={i} className="border-l-2 border-primary/40 pl-3">
                      <div className="font-medium">{d.title}</div>
                      <div className="text-muted-foreground">{d.detail}</div>
                      {d.refs?.length ? (
                        <div className="mt-1 text-xs text-muted-foreground/80 font-mono">
                          {d.refs.join(", ")}
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="qa" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Generate questions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1.5">
                  <span className="text-sm font-medium">Position</span>
                  <Select value={position} onValueChange={setPosition}>
                    <SelectTrigger className="w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="swe_generic">SWE (generic)</SelectItem>
                      <SelectItem value="applied_ai">Applied AI</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <span className="text-sm font-medium">Levels</span>
                  <div className="flex flex-wrap gap-1.5">
                    {ALL_LEVELS.map((l) => {
                      const active = !!levels[l];
                      return (
                        <button
                          key={l}
                          type="button"
                          onClick={() =>
                            setLevels((s) => ({ ...s, [l]: !s[l] }))
                          }
                          className={
                            "rounded-full px-3 py-1 text-xs font-medium border transition-colors " +
                            (active
                              ? "bg-primary text-primary-foreground border-primary"
                              : "bg-background hover:bg-accent")
                          }
                        >
                          {l.replace("_", " ")}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <Button onClick={generateQA}>
                  <Wand2 className="h-4 w-4" /> Generate
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              {qaSets.length === 0 ? (
                <EmptyState
                  title="No QA sets yet"
                  description="Generated sets will appear here. They take ~30s per level."
                />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Position</TableHead>
                      <TableHead>Level</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Questions</TableHead>
                      <TableHead className="text-right" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {qaSets.map((s) => (
                      <TableRow key={s.id}>
                        <TableCell className="capitalize">
                          {s.position.replace("_", " ")}
                        </TableCell>
                        <TableCell className="capitalize">
                          {s.level.replace("_", " ")}
                        </TableCell>
                        <TableCell>
                          <StatusPill status={s.status} />
                        </TableCell>
                        <TableCell>{s.total}</TableCell>
                        <TableCell className="text-right">
                          <Button asChild size="sm" variant="ghost">
                            <Link to={`/qa-sets/${s.id}`}>
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
        </TabsContent>

        <TabsContent value="diagrams" className="space-y-4">
          {diagrams.length === 0 ? (
            <Card>
              <CardContent>
                <EmptyState
                  title="No diagrams yet"
                  description="Mermaid diagrams are produced during ingestion."
                />
              </CardContent>
            </Card>
          ) : (
            diagrams.map((d) => (
              <Card key={d.id}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    {d.name}
                    <Badge variant="muted">{d.kind}</Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs font-mono leading-relaxed">
                    {d.mermaid}
                  </pre>
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="files">
          <Card>
            <CardContent className="p-0">
              {files.length === 0 ? (
                <EmptyState
                  title="No files yet"
                  description="Indexed files appear here as ingestion progresses."
                />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Path</TableHead>
                      <TableHead>Lang</TableHead>
                      <TableHead className="text-right">Bytes</TableHead>
                      <TableHead>Summary</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {files.map((f) => (
                      <TableRow key={f.id}>
                        <TableCell className="font-mono text-xs">
                          {f.rel_path}
                        </TableCell>
                        <TableCell>
                          {f.language ? (
                            <Badge variant="muted">{f.language}</Badge>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {f.bytes}
                        </TableCell>
                        <TableCell className="text-muted-foreground max-w-md truncate">
                          {f.summary}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
