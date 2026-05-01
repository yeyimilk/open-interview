import { Badge } from "../ui/badge";

const MAP: Record<string, "default" | "secondary" | "success" | "warning" | "destructive" | "muted"> = {
  pending: "muted",
  queued: "muted",
  running: "default",
  ingesting: "default",
  ready: "success",
  done: "success",
  ended: "secondary",
  active: "default",
  failed: "destructive",
  error: "destructive",
};

export function StatusPill({ status }: { status: string }) {
  const variant = MAP[status] || "secondary";
  return (
    <Badge variant={variant} className="capitalize">
      {status.replaceAll("_", " ")}
    </Badge>
  );
}
