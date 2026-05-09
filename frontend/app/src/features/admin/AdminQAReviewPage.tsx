import { Check, RefreshCw, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { QASetOut, api } from "../../api/client";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";

export function AdminQAReviewPage() {
  const [sets, setSets] = useState<QASetOut[]>([]);
  const [reviewStatus, setReviewStatus] = useState("all");
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setSets(
        await api.adminListQASets({
          review_status: reviewStatus === "all" ? undefined : reviewStatus,
          limit: 200,
        })
      );
    } catch (e) {
      toast.error("Failed to load QA sets", { description: (e as Error).message });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewStatus]);

  async function review(set: QASetOut, status: string) {
    try {
      const updated = await api.adminReviewQASet(set.id, { review_status: status });
      setSets((prev) => prev.map((row) => (row.id === set.id ? updated : row)));
    } catch (e) {
      toast.error("Review failed", { description: (e as Error).message });
    }
  }

  async function regenerate(set: QASetOut) {
    try {
      const updated = await api.adminRegenerateQASet(set.id);
      setSets((prev) => prev.map((row) => (row.id === set.id ? updated : row)));
      toast.success("Regeneration queued");
    } catch (e) {
      toast.error("Regeneration failed", { description: (e as Error).message });
    }
  }

  return (
    <div>
      <PageHeader
        title="QA review"
        description="Review generated question sets and queue regeneration when quality slips."
        actions={
          <>
            <Select value={reviewStatus} onValueChange={setReviewStatus}>
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All reviews</SelectItem>
                <SelectItem value="unreviewed">Unreviewed</SelectItem>
                <SelectItem value="approved">Approved</SelectItem>
                <SelectItem value="needs_work">Needs work</SelectItem>
                <SelectItem value="rejected">Rejected</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </>
        }
      />
      <div className="space-y-2">
        {sets.map((set) => (
          <Card key={set.id}>
            <CardContent className="flex flex-wrap items-center justify-between gap-3 p-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/qa-sets/${set.id}`} className="font-medium hover:underline">
                    {set.position.replace("_", " ")} · {set.level.replace("_", " ")}
                  </Link>
                  <StatusPill status={set.status} />
                  <Badge variant="outline">{set.scope}</Badge>
                  <Badge variant={set.review_status === "approved" ? "success" : "muted"}>
                    {set.review_status.replace("_", " ")}
                  </Badge>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {set.total} questions · run {set.generation_run?.status ?? "not started"}
                  {set.error ? ` · ${set.error}` : ""}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => void review(set, "approved")}>
                  <Check className="h-4 w-4" /> Approve
                </Button>
                <Button size="sm" variant="outline" onClick={() => void review(set, "needs_work")}>
                  <X className="h-4 w-4" /> Needs work
                </Button>
                <Button size="sm" variant="outline" onClick={() => void regenerate(set)}>
                  <RotateCcw className="h-4 w-4" /> Regenerate
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {!loading && sets.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-sm text-muted-foreground">
              No QA sets match this filter.
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  );
}
