import { ArrowLeft, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { QASetDetail, api } from "../../api/client";
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
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";

export function QASetPage() {
  const { id = "" } = useParams();
  const [set, setSet] = useState<QASetDetail | null>(null);

  async function load() {
    try {
      setSet(await api.getQASet(id));
    } catch (e) {
      toast.error("Failed to load", { description: (e as Error).message });
    }
  }

  useEffect(() => {
    if (!id) return;
    void load();
    const t = setInterval(() => {
      if (!set || set.status !== "ready") void load();
    }, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, set?.status]);

  async function regenerate() {
    if (!set) return;
    try {
      await api.regenerateQASet(set.id);
      toast.success("Regeneration queued");
      await load();
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    }
  }

  if (!set) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-1/3" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const byCat: Record<string, typeof set.items> = {};
  for (const it of set.items) {
    (byCat[it.category] = byCat[it.category] || []).push(it);
  }
  const targetLink =
    set.scope === "resume" && set.resume_id
      ? { to: `/resumes/${set.resume_id}`, label: "Resume" }
      : set.project_id
        ? { to: `/projects/${set.project_id}`, label: "Project" }
        : null;

  return (
    <div>
      <PageHeader
        title={
          <span>
            <span className="capitalize">{set.position.replace("_", " ")}</span>{" "}
            <span className="text-muted-foreground">·</span>{" "}
            <span className="capitalize">{set.level.replace("_", " ")}</span>
          </span>
        }
        description={`${set.total} questions across ${Object.keys(byCat).length} categories`}
        actions={
          <>
            <StatusPill status={set.status} />
            <Badge variant={set.review_status === "approved" ? "success" : "muted"}>
              {set.review_status.replace("_", " ")}
            </Badge>
            {targetLink && (
              <Button asChild variant="outline">
                <Link to={targetLink.to}>
                  <ArrowLeft className="h-4 w-4" /> {targetLink.label}
                </Link>
              </Button>
            )}
            <Button variant="outline" onClick={regenerate}>
              <RefreshCw className="h-4 w-4" /> Regenerate
            </Button>
          </>
        }
      />

      {set.status !== "ready" && (
        <Card className="mb-4 border-primary/30 bg-primary/5">
          <CardContent className="py-4 text-sm text-muted-foreground">
            Generation in progress. Page auto-refreshes every 4 seconds.
          </CardContent>
        </Card>
      )}
      {set.generation_run ? (
        <Card className="mb-4">
          <CardContent className="py-3 text-sm text-muted-foreground">
            Generation run {set.generation_run.status}
            {set.generation_run.attempt ? ` · attempt ${set.generation_run.attempt}` : ""}
            {set.generation_run.error ? ` · ${set.generation_run.error}` : ""}
          </CardContent>
        </Card>
      ) : null}

      <div className="space-y-4">
        {Object.entries(byCat).map(([cat, items]) => (
          <Card key={cat}>
            <CardHeader>
              <CardTitle className="capitalize flex items-center gap-2">
                {cat.replace("_", " ")}
                <Badge variant="muted">{items.length}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <Accordion type="multiple" className="w-full">
                {items.map((it) => (
                  <AccordionItem key={it.id} value={it.id}>
                    <AccordionTrigger className="text-left hover:no-underline gap-3">
                      <span className="text-sm font-normal flex-1">
                        {it.question}
                      </span>
                    </AccordionTrigger>
                    <AccordionContent className="space-y-3 pt-2">
                      <div className="rounded-md border bg-muted/30 p-3">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
                          Ideal answer
                        </div>
                        <div className="text-sm whitespace-pre-wrap">
                          {it.ideal_answer}
                        </div>
                      </div>
                      {it.evidence.length > 0 && (
                        <div className="text-sm">
                          <div className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
                            Evidence
                          </div>
                          <ul className="space-y-0.5">
                            {it.evidence.map((e, i) => (
                              <li
                                key={i}
                                className="font-mono text-xs text-muted-foreground"
                              >
                                {e.rel_path}:{e.start_line}-{e.end_line}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <div className="flex items-center gap-2 pt-1">
                        <Badge variant="outline">
                          Difficulty {it.difficulty}/5
                        </Badge>
                        {it.tags.map((t) => (
                          <Badge key={t} variant="muted">
                            {t}
                          </Badge>
                        ))}
                      </div>
                      {it.follow_up_axes.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          {it.follow_up_axes.map((axis) => (
                            <Badge key={axis} variant="outline">
                              {axis.replace(/_/g, " ")}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
