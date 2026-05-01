import { ArrowRight, FolderUp, Loader2, Plus, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ProjectOut, api } from "../../api/client";
import { EmptyState } from "../../components/common/EmptyState";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      setProjects(await api.listProjects());
    } catch (e) {
      toast.error("Failed to load projects", {
        description: (e as Error).message,
      });
    }
  }

  useEffect(() => {
    void load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      await api.uploadProject(name || file.name.replace(/\.zip$/i, ""), file);
      toast.success("Upload complete", {
        description: "Ingestion started in the background.",
      });
      setName("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      setOpen(false);
      await load();
    } catch (ex) {
      toast.error("Upload failed", {
        description: (ex as Error).message,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Projects"
        description="Upload codebases. We chunk, embed, summarize, and generate interview questions for each level."
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" /> New project
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Upload a project</DialogTitle>
                <DialogDescription>
                  Drop a .zip of your source code. Ingestion runs in the
                  background.
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={upload} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="proj-name">Project name</Label>
                  <Input
                    id="proj-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="(defaults to the .zip filename)"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="proj-file">Source archive</Label>
                  <label
                    htmlFor="proj-file"
                    className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-input p-6 text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors cursor-pointer"
                  >
                    <Upload className="h-5 w-5" />
                    {file ? (
                      <span className="font-medium text-foreground">
                        {file.name}{" "}
                        <span className="text-muted-foreground">
                          ({(file.size / 1024 / 1024).toFixed(1)} MB)
                        </span>
                      </span>
                    ) : (
                      <span>Click to select a .zip file</span>
                    )}
                    <input
                      id="proj-file"
                      ref={fileRef}
                      type="file"
                      accept=".zip"
                      onChange={(e) => setFile(e.target.files?.[0] || null)}
                      className="hidden"
                    />
                  </label>
                </div>
                <DialogFooter>
                  <Button
                    variant="outline"
                    type="button"
                    onClick={() => setOpen(false)}
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
                        <Upload className="h-4 w-4" /> Upload & ingest
                      </>
                    )}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        }
      />

      <Card>
        <CardContent className="p-0">
          {projects.length === 0 ? (
            <EmptyState
              icon={FolderUp}
              title="No projects yet"
              description="Upload your first codebase to start practicing with grounded, evidence-backed questions."
              action={
                <Button onClick={() => setOpen(true)}>
                  <Plus className="h-4 w-4" /> Upload project
                </Button>
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {projects.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">{p.name}</TableCell>
                    <TableCell>
                      <StatusPill status={p.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(p.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button asChild size="sm" variant="ghost">
                        <Link to={`/projects/${p.id}`}>
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
    </div>
  );
}
