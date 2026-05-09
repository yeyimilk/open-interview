import {
  ArrowRight,
  GraduationCap,
  MessageSquare,
  Mic,
  RefreshCw,
  Search,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  ChatMessageOut,
  ChatSessionOut,
  ProjectOut,
  api,
} from "../../api/client";
import { EmptyState } from "../../components/common/EmptyState";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import { Skeleton } from "../../components/ui/skeleton";

type HistoryMode = "general" | "mentor" | "interviewer";
type ModeFilter = "all" | HistoryMode;

type HistorySession = ChatSessionOut & {
  historyMode: HistoryMode;
};

const MODE_META: Record<
  HistoryMode,
  {
    label: string;
    route: (id: string) => string;
    icon: React.ElementType;
  }
> = {
  general: {
    label: "Chat",
    route: (id) => `/chat/${id}`,
    icon: MessageSquare,
  },
  mentor: {
    label: "Mentor",
    route: (id) => `/mentor/${id}`,
    icon: GraduationCap,
  },
  interviewer: {
    label: "Interview",
    route: (id) => `/interviewer/${id}`,
    icon: Mic,
  },
};

const ALL = "all";

export function ChatHistoryPage() {
  const [sessions, setSessions] = useState<HistorySession[] | null>(null);
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<ModeFilter>(ALL);
  const [projectId, setProjectId] = useState(ALL);
  const [messageCache, setMessageCache] = useState<Record<string, string>>({});
  const [searchingMessages, setSearchingMessages] = useState(false);

  async function load() {
    try {
      const [general, mentor, interviewer, projectList] = await Promise.all([
        api.listGeneralSessions(),
        api.listMentorSessions(),
        api.listInterviewerSessions(),
        api.listProjects(),
      ]);
      setProjects(projectList);
      setSessions(
        [
          ...general.map((s) => ({ ...s, historyMode: "general" as const })),
          ...mentor.map((s) => ({ ...s, historyMode: "mentor" as const })),
          ...interviewer.map((s) => ({
            ...s,
            historyMode: "interviewer" as const,
          })),
        ].sort(
          (a, b) =>
            new Date(b.created_at).getTime() -
            new Date(a.created_at).getTime()
        )
      );
    } catch (e) {
      toast.error("Failed to load history", {
        description: (e as Error).message,
      });
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!sessions || query.trim().length < 2) {
      setSearchingMessages(false);
      return;
    }
    const missing = sessions.filter((session) => !(session.id in messageCache));
    if (missing.length === 0) {
      setSearchingMessages(false);
      return;
    }
    let cancelled = false;

    async function hydrateMessages() {
      setSearchingMessages(true);
      const next: Record<string, string> = {};
      for (const session of missing.slice(0, 80)) {
        if (cancelled) break;
        try {
          const messages = await listMessages(session);
          if (cancelled) break;
          next[session.id] = messages
            .map((m) => `${m.role}: ${m.content}`)
            .join("\n");
        } catch {
          next[session.id] = "";
        }
      }
      if (!cancelled) {
        setMessageCache((prev) => ({ ...prev, ...next }));
        setSearchingMessages(false);
      }
    }

    void hydrateMessages();
    return () => {
      cancelled = true;
    };
  }, [messageCache, query, sessions]);

  const projectNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const project of projects) map[project.id] = project.name;
    return map;
  }, [projects]);

  const results = useMemo(() => {
    const q = normalize(query);
    return (sessions ?? [])
      .filter((session) => mode === ALL || session.historyMode === mode)
      .filter((session) => {
        if (projectId === ALL) return true;
        return getProjectId(session) === projectId;
      })
      .map((session) => {
        const projectName = projectNameById[getProjectId(session) ?? ""] ?? null;
        const messageText = messageCache[session.id] ?? "";
        const searchable = normalize(
          [
            session.title,
            session.status,
            session.historyMode,
            projectName,
            targetText(session),
            messageText,
          ]
            .filter(Boolean)
            .join(" ")
        );
        return {
          session,
          projectName,
          snippet: q ? makeSnippet(messageText, query) : "",
          searchable,
        };
      })
      .filter((row) => !q || row.searchable.includes(q));
  }, [messageCache, mode, projectId, projectNameById, query, sessions]);

  return (
    <div>
      <PageHeader
        title="Chat history"
        description="Search general chats, mentor sessions, and mock interviews from one place."
        actions={
          <Button variant="outline" onClick={() => void load()}>
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      <Card className="mb-4">
        <CardContent className="grid gap-3 p-3 md:grid-cols-[1fr_180px_220px]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search titles, context, and message text"
              className="pl-9"
            />
          </div>
          <Select value={mode} onValueChange={(value) => setMode(value as ModeFilter)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All modes</SelectItem>
              <SelectItem value="general">Chat</SelectItem>
              <SelectItem value="mentor">Mentor</SelectItem>
              <SelectItem value="interviewer">Interview</SelectItem>
            </SelectContent>
          </Select>
          <Select value={projectId} onValueChange={setProjectId}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All projects</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {sessions === null ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : results.length === 0 ? (
        <Card>
          <CardContent className="py-10">
            <EmptyState
              icon={Search}
              title="No sessions found"
              description="Try a different search, mode, or project filter."
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>{results.length} sessions</span>
            {searchingMessages ? (
              <span>Searching message text...</span>
            ) : query.trim().length >= 2 ? (
              <span>Message text included</span>
            ) : null}
          </div>
          {results.map(({ session, projectName, snippet }) => (
            <HistoryRow
              key={session.id}
              session={session}
              projectName={projectName}
              snippet={snippet}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function HistoryRow({
  session,
  projectName,
  snippet,
}: {
  session: HistorySession;
  projectName: string | null;
  snippet: string;
}) {
  const meta = MODE_META[session.historyMode];
  const Icon = meta.icon;
  const target = targetText(session);
  return (
    <Link
      to={meta.route(session.id)}
      className="block rounded-lg border bg-card p-3 transition-colors hover:border-primary/40 hover:bg-accent/30"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-sm font-semibold">
                {session.title || "Untitled"}
              </h3>
              <Badge variant="muted">{meta.label}</Badge>
              <StatusPill status={session.status} />
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>{session.turn_count} turns</span>
              <span>{new Date(session.created_at).toLocaleString()}</span>
              {projectName ? <span>Project: {projectName}</span> : null}
              {target ? <span>{target}</span> : null}
            </div>
            {snippet ? (
              <p className="line-clamp-2 text-sm text-muted-foreground">
                {snippet}
              </p>
            ) : null}
          </div>
        </div>
        <ArrowRight className="mt-2 h-4 w-4 shrink-0 text-muted-foreground" />
      </div>
    </Link>
  );
}

async function listMessages(session: HistorySession): Promise<ChatMessageOut[]> {
  if (session.historyMode === "mentor") {
    return api.listMentorMessages(session.id);
  }
  if (session.historyMode === "interviewer") {
    return api.listInterviewerMessages(session.id);
  }
  return api.listGeneralMessages(session.id);
}

function getProjectId(session: HistorySession): string | null {
  if (session.project_id) return session.project_id;
  const target = session.target;
  if (target && typeof target === "object" && typeof target.project_id === "string") {
    return target.project_id;
  }
  return null;
}

function targetText(session: HistorySession): string {
  const target = session.target;
  if (!target || typeof target !== "object") return "";
  const parts = [
    typeof target.position === "string"
      ? target.position.replaceAll("_", " ")
      : "",
    typeof target.level === "string" ? target.level.replaceAll("_", " ") : "",
    typeof target.resume_filename === "string"
      ? `Resume: ${target.resume_filename}`
      : "",
    typeof target.target_company === "string"
      ? `Company: ${target.target_company}`
      : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function makeSnippet(text: string, query: string): string {
  const q = query.trim().toLowerCase();
  if (!q || !text) return "";
  const lower = text.toLowerCase();
  const idx = lower.indexOf(q);
  if (idx === -1) return "";
  const start = Math.max(0, idx - 90);
  const end = Math.min(text.length, idx + q.length + 140);
  const prefix = start > 0 ? "..." : "";
  const suffix = end < text.length ? "..." : "";
  return `${prefix}${text.slice(start, end).replace(/\s+/g, " ")}${suffix}`;
}
