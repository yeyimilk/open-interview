import { ArrowLeft, ThumbsDown, ThumbsUp, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { InterviewEvaluationOut, api } from "../../api/client";
import { PageHeader } from "../../components/common/PageHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { Progress } from "../../components/ui/progress";
import { Skeleton } from "../../components/ui/skeleton";

function scoreVariant(s: number): "success" | "warning" | "destructive" {
  if (s >= 4) return "success";
  if (s >= 2.5) return "warning";
  return "destructive";
}

export function EvaluationPage() {
  const { id = "" } = useParams();
  const [ev, setEv] = useState<InterviewEvaluationOut | null>(null);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      try {
        setEv(await api.getInterviewerEvaluation(id));
      } catch (e) {
        toast.error("Failed to load evaluation", {
          description: (e as Error).message,
        });
      }
    })();
  }, [id]);

  if (!ev) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-1/3" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const overall = ev.overall_score;
  const overallPct = (overall / 5) * 100;
  const variant = scoreVariant(overall);

  return (
    <div>
      <PageHeader
        title="Evaluation"
        description="Aggregated rubric, strengths, gaps, and suggested practice."
        actions={
          <Button asChild variant="outline">
            <Link to={`/interviewer/${id}`}>
              <ArrowLeft className="h-4 w-4" /> Session
            </Link>
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardDescription>Overall</CardDescription>
            <CardTitle className="text-4xl tabular-nums">
              {overall.toFixed(1)}
              <span className="text-base text-muted-foreground font-medium">
                {" "}
                / 5
              </span>
              <Badge variant={variant} className="ml-3 align-middle">
                {variant === "success"
                  ? "Strong"
                  : variant === "warning"
                  ? "Solid"
                  : "Needs work"}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Progress value={overallPct} />
            <p className="text-sm whitespace-pre-wrap text-muted-foreground">
              {ev.summary}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Category scores</CardTitle>
          </CardHeader>
          <CardContent>
            {!ev.scores || Object.keys(ev.scores).length === 0 ? (
              <p className="text-sm text-muted-foreground italic">
                No category breakdown.
              </p>
            ) : (
              <ul className="space-y-3">
                {Object.entries(ev.scores).map(([k, v]) => (
                  <li key={k} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="capitalize">
                        {k.replace("_", " ")}
                      </span>
                      <span className="tabular-nums font-medium">
                        {v.toFixed(1)}
                      </span>
                    </div>
                    <Progress value={(v / 5) * 100} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 mt-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <ThumbsUp className="h-4 w-4 text-success" />
              Strengths ({ev.strengths.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {ev.strengths.length === 0 ? (
              <p className="text-sm text-muted-foreground italic">None.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {ev.strengths.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-success">·</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <ThumbsDown className="h-4 w-4 text-destructive" />
              Weaknesses ({ev.weaknesses.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {ev.weaknesses.length === 0 ? (
              <p className="text-sm text-muted-foreground italic">None.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {ev.weaknesses.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-destructive">·</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" /> Suggested practice
          </CardTitle>
          <CardDescription>
            A focused plan -- what to work on, why, and how.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {ev.suggested_practice.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">None.</p>
          ) : (
            <ul className="space-y-3">
              {ev.suggested_practice.map((p, i) => (
                <li
                  key={i}
                  className="rounded-lg border p-3 space-y-1 bg-muted/30"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{p.area}</Badge>
                  </div>
                  <p className="text-sm">{p.why}</p>
                  <p className="text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">
                      Next step:
                    </span>{" "}
                    {p.next_step}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
