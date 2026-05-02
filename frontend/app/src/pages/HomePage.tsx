import {
  ArrowRight,
  FileText,
  Folders,
  GraduationCap,
  KeyRound,
  MessageSquare,
  Mic,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";

const STEPS = [
  {
    title: "Add your LLM API key",
    description:
      "OpenAI, Anthropic, or any OpenAI-compatible endpoint. Stays encrypted at rest.",
    to: "/settings",
    icon: KeyRound,
  },
  {
    title: "Upload a project",
    description:
      "We ingest, summarize, and auto-generate QA per level (junior to tech-lead).",
    to: "/projects",
    icon: Folders,
  },
  {
    title: "Upload your resume",
    description:
      "Claims are grounded against your project code so you can speak with evidence.",
    to: "/resumes",
    icon: FileText,
  },
  {
    title: "Open a Chat",
    description:
      "Workspace-aware general assistant. Same agent that powers WhatsApp /chat.",
    to: "/chat",
    icon: MessageSquare,
  },
  {
    title: "Talk to the Mentor",
    description:
      "Project-scoped coach with read-only access to your repo. Browses files when needed.",
    to: "/mentor",
    icon: GraduationCap,
  },
  {
    title: "Run a mock interview",
    description:
      "Real-time evaluation, follow-up probes, and a final rubric with practice plan.",
    to: "/interviewer/start",
    icon: Mic,
  },
];

export function HomePage() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">
          Welcome back, {user.display_name?.split(" ")[0] || "there"}.
        </h1>
        <p className="text-muted-foreground">
          Pick up where you left off, or run through the quickstart below.
        </p>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {STEPS.map((s, i) => {
          const Icon = s.icon;
          return (
            <Link to={s.to} key={s.to} className="group">
              <Card className="h-full transition-all hover:shadow-md hover:border-primary/40">
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="grid h-10 w-10 place-items-center rounded-xl bg-primary/10 text-primary">
                      <Icon className="h-5 w-5" />
                    </div>
                    <span className="text-xs text-muted-foreground">
                      Step {i + 1}
                    </span>
                  </div>
                  <CardTitle className="pt-3">{s.title}</CardTitle>
                  <CardDescription>{s.description}</CardDescription>
                </CardHeader>
                <CardContent className="text-sm font-medium text-primary inline-flex items-center gap-1 opacity-70 group-hover:opacity-100 transition-opacity">
                  Open <ArrowRight className="h-3.5 w-3.5" />
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </section>
    </div>
  );
}
