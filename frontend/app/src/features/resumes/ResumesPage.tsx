import {
  Download,
  ExternalLink,
  Eye,
  FileText,
  Loader2,
  MoreVertical,
  ScanText,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ProjectOut, ResumeOut, api } from "../../api/client";
import { EmptyState } from "../../components/common/EmptyState";
import { PageHeader } from "../../components/common/PageHeader";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../components/ui/dropdown-menu";
import { Label } from "../../components/ui/label";
import { Skeleton } from "../../components/ui/skeleton";

interface ViewerState {
  open: boolean;
  resume: ResumeOut | null;
  url: string | null;
  contentType: string;
  filename: string;
  loading: boolean;
}

const initialViewer: ViewerState = {
  open: false,
  resume: null,
  url: null,
  contentType: "",
  filename: "",
  loading: false,
};

export function ResumesPage() {
  const nav = useNavigate();
  const [items, setItems] = useState<ResumeOut[] | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [viewer, setViewer] = useState<ViewerState>(initialViewer);
  const objectUrlRef = useRef<string | null>(null);

  function revokeUrl() {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }

  useEffect(() => () => revokeUrl(), []);

  async function load() {
    try {
      setItems(await api.listResumes());
    } catch (e) {
      toast.error("Failed to load resumes", {
        description: (e as Error).message,
      });
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function fetchFile(resume: ResumeOut) {
    revokeUrl();
    const { blob, contentType, filename } = await api.fetchResumeFile(
      resume.id,
      true
    );
    const url = URL.createObjectURL(blob);
    objectUrlRef.current = url;
    return { url, contentType, filename };
  }

  async function openResume(resume: ResumeOut) {
    setViewer({
      open: true,
      resume,
      url: null,
      contentType: "",
      filename: resume.original_filename,
      loading: true,
    });
    try {
      const { url, contentType, filename } = await fetchFile(resume);
      setViewer({
        open: true,
        resume,
        url,
        contentType,
        filename,
        loading: false,
      });
    } catch (e) {
      toast.error("Could not open resume", {
        description: (e as Error).message,
      });
      setViewer(initialViewer);
    }
  }

  function closeViewer(open: boolean) {
    if (!open) {
      revokeUrl();
      setViewer(initialViewer);
    }
  }

  async function downloadResume(resume: ResumeOut) {
    try {
      // Auth-aware fetch (handles 401 -> refresh) before triggering the download.
      const { blob, filename } = await api.fetchResumeFile(resume.id, false);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // Revoke after a short delay so the browser has a chance to start the download.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error("Download failed", { description: (e as Error).message });
    }
  }

  async function openInNewTab(resume: ResumeOut) {
    try {
      // Always re-run an auth-aware fetch so a stale or revoked URL is impossible.
      const { blob } = await api.fetchResumeFile(resume.id, true);
      const url = URL.createObjectURL(blob);
      const w = window.open(url, "_blank", "noopener,noreferrer");
      if (!w) {
        toast.error("Pop-up blocked", {
          description: "Allow pop-ups for this site to open the file.",
        });
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error("Could not open file", {
        description: (e as Error).message,
      });
    }
  }

  async function remove(resume: ResumeOut) {
    if (!confirm("Delete this resume? Claim grounding will be removed too."))
      return;
    try {
      await api.deleteResume(resume.id);
      toast.success("Resume deleted");
      await load();
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    }
  }

  return (
    <div>
      <PageHeader
        title="Resumes"
        description="Upload one or more resumes. The interviewer grounds claims against your project code."
        actions={
          <UploadDialog
            open={uploadOpen}
            onOpenChange={setUploadOpen}
            onUploaded={(id) => {
              setUploadOpen(false);
              void load();
              nav(`/resumes/${id}`);
            }}
            trigger={
              <Button>
                <Upload className="h-4 w-4" /> Upload resume
              </Button>
            }
          />
        }
      />

      {items === null ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="py-10">
            <EmptyState
              icon={FileText}
              title="No resumes yet"
              description="Upload a resume to start grounding claims against your projects."
              action={
                <Button onClick={() => setUploadOpen(true)}>
                  <Upload className="h-4 w-4" /> Upload resume
                </Button>
              }
            />
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((r) => (
            <ResumeCard
              key={r.id}
              resume={r}
              onOpen={() => openResume(r)}
              onDownload={() => downloadResume(r)}
              onViewDetails={() => nav(`/resumes/${r.id}`)}
              onDelete={() => remove(r)}
            />
          ))}
        </div>
      )}

      <FileViewerDialog
        state={viewer}
        onOpenChange={closeViewer}
        onOpenInNewTab={openInNewTab}
      />
    </div>
  );
}

function ResumeCard({
  resume,
  onOpen,
  onDownload,
  onViewDetails,
  onDelete,
}: {
  resume: ResumeOut;
  onOpen: () => void;
  onDownload: () => void;
  onViewDetails: () => void;
  onDelete: () => void;
}) {
  const ext = resume.original_filename.split(".").pop()?.toLowerCase() || "";
  return (
    <Card
      onClick={onOpen}
      className="group relative cursor-pointer transition-colors hover:border-primary/40 hover:bg-accent/30"
    >
      <CardHeader className="flex-row items-start gap-3 space-y-0 pb-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <FileText className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="text-sm font-semibold truncate">
            {resume.original_filename}
          </CardTitle>
          <CardDescription className="text-xs">
            {ext.toUpperCase() || "FILE"} ·{" "}
            {new Date(resume.created_at).toLocaleDateString()}
          </CardDescription>
        </div>
        <div onClick={(e) => e.stopPropagation()}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                aria-label="More actions"
              >
                <MoreVertical className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  onOpen();
                }}
              >
                <Eye className="h-4 w-4" /> Open
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  onDownload();
                }}
              >
                <Download className="h-4 w-4" /> Download
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  onViewDetails();
                }}
              >
                <ScanText className="h-4 w-4" /> View parsed details
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={(e) => {
                  e.preventDefault();
                  onDelete();
                }}
              >
                <Trash2 className="h-4 w-4" /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">
        Uploaded {new Date(resume.created_at).toLocaleString()}
      </CardContent>
    </Card>
  );
}

// ---------- File viewer ----------

function FileViewerDialog({
  state,
  onOpenChange,
  onOpenInNewTab,
}: {
  state: ViewerState;
  onOpenChange: (open: boolean) => void;
  onOpenInNewTab: (resume: ResumeOut) => void;
}) {
  const previewable =
    state.contentType.includes("pdf") ||
    state.contentType.startsWith("text/") ||
    state.contentType.includes("markdown");
  return (
    <Dialog open={state.open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-[95vw] h-[90vh] p-0 gap-0 flex flex-col">
        <DialogHeader className="px-5 py-3 pr-14 border-b flex-row items-center justify-between gap-3 space-y-0">
          <DialogTitle className="flex items-center gap-2 text-base truncate min-w-0">
            <FileText className="h-4 w-4 text-primary shrink-0" />
            <span className="truncate">{state.filename}</span>
          </DialogTitle>
          {state.resume ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="shrink-0 text-muted-foreground hover:text-foreground"
              onClick={() => onOpenInNewTab(state.resume!)}
              disabled={state.loading}
            >
              <ExternalLink className="h-3.5 w-3.5" /> Open in new tab
            </Button>
          ) : null}
        </DialogHeader>
        <div className="flex-1 min-h-0 bg-muted/40">
          {state.loading || !state.url ? (
            <div className="grid place-items-center h-full text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : previewable ? (
            <iframe
              src={state.url}
              title={state.filename}
              className="h-full w-full border-0 bg-background"
            />
          ) : (
            <div className="grid place-items-center h-full text-center px-6 gap-3">
              <FileText className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm text-muted-foreground max-w-sm">
                Browsers can't preview {state.contentType || "this file type"}{" "}
                inline. Open it in a new tab or download it.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  state.resume && onOpenInNewTab(state.resume)
                }
              >
                <ExternalLink className="h-4 w-4" /> Open in new tab
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Upload dialog ----------

function UploadDialog({
  open,
  onOpenChange,
  onUploaded,
  trigger,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onUploaded: (id: string) => void;
  trigger: React.ReactNode;
}) {
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      try {
        setProjects(await api.listProjects());
      } catch (e) {
        toast.error("Failed to load projects", {
          description: (e as Error).message,
        });
      }
    })();
  }, [open]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const ids = Object.entries(selected)
        .filter(([, v]) => v)
        .map(([k]) => k);
      const r = await api.uploadResume(file, ids);
      toast.success("Resume uploaded", {
        description: "Parsing and grounding started.",
      });
      onUploaded(r.id);
      setFile(null);
      setSelected({});
    } catch (ex) {
      toast.error("Upload failed", { description: (ex as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Upload resume</DialogTitle>
          <DialogDescription>
            Supported: .txt, .md, .pdf, .docx
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <label className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-input p-6 text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors cursor-pointer">
            <FileText className="h-6 w-6" />
            {file ? (
              <span className="font-medium text-foreground text-center">
                {file.name}
                <span className="ml-1 text-muted-foreground">
                  ({(file.size / 1024).toFixed(1)} KB)
                </span>
              </span>
            ) : (
              <span>Click to select a resume file</span>
            )}
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md,.markdown,.pdf,.docx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="hidden"
            />
          </label>

          <div className="space-y-2">
            <Label>Ground claims against these projects</Label>
            {projects.length === 0 ? (
              <p className="text-sm text-muted-foreground italic">
                Upload a project first to enable grounding.
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {projects.map((p) => {
                  const active = !!selected[p.id];
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() =>
                        setSelected((s) => ({ ...s, [p.id]: !s[p.id] }))
                      }
                      className={
                        "rounded-full px-3 py-1 text-xs font-medium border transition-colors " +
                        (active
                          ? "bg-primary text-primary-foreground border-primary"
                          : "bg-background hover:bg-accent")
                      }
                    >
                      {p.name}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !file}>
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Uploading...
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" /> Upload & parse
                </>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
