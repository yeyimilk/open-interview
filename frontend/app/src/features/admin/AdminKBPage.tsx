import { Database, FileText, FileUp, FolderOpen, ListChecks, Play, RefreshCw, Tags } from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type InputHTMLAttributes,
} from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  CommonKBDocumentOut,
  CommonKBItemOut,
  CommonKBSourceOut,
  CommonKBSpaceOut,
  api,
} from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
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
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";

const DEFAULT_SPACES = [
  ["leetcode", "LeetCode / DSA"],
  ["system_design", "System Design"],
  ["ai_design", "AI Design"],
  ["architecture", "Architecture"],
  ["company_experience", "Company Experience"],
  ["behavioral", "Behavioral"],
];

const SUPPORTED_KB_ACCEPT = ".md,.txt,.pdf,.docx,.json,.csv,.html,.htm";
const SUPPORTED_KB_EXTENSIONS = new Set(
  SUPPORTED_KB_ACCEPT.split(",").map((ext) => ext.trim())
);

const DIRECTORY_INPUT_PROPS = {
  webkitdirectory: "true",
  directory: "true",
} as InputHTMLAttributes<HTMLInputElement> & {
  webkitdirectory: string;
  directory: string;
};

interface FolderUploadFile {
  file: File;
  path: string;
}

type BrowserFileHandle = {
  kind: "file";
  name: string;
  getFile: () => Promise<File>;
};

type BrowserDirectoryHandle = {
  kind: "directory";
  name: string;
  values: () => AsyncIterable<BrowserFileHandle | BrowserDirectoryHandle>;
};

type BrowserWindowWithDirectoryPicker = Window & {
  showDirectoryPicker?: () => Promise<BrowserDirectoryHandle>;
};

export function AdminKBPage() {
  const { user } = useAuth();
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const [spaces, setSpaces] = useState<CommonKBSpaceOut[]>([]);
  const [sources, setSources] = useState<CommonKBSourceOut[]>([]);
  const [docs, setDocs] = useState<CommonKBDocumentOut[]>([]);
  const [items, setItems] = useState<CommonKBItemOut[]>([]);
  const [spaceKey, setSpaceKey] = useState("leetcode");
  const [file, setFile] = useState<File | null>(null);
  const [folderFiles, setFolderFiles] = useState<FolderUploadFile[]>([]);
  const [documentTags, setDocumentTags] = useState("");
  const [createEmbeddings, setCreateEmbeddings] = useState(true);
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [manualQuestion, setManualQuestion] = useState("");
  const [busy, setBusy] = useState(false);

  const sourceForSpace = useMemo(
    () => sources.filter((s) => s.space_id === spaces.find((sp) => sp.key === spaceKey)?.id),
    [sources, spaces, spaceKey]
  );

  async function load() {
    if (!user?.is_admin) return;
    const [sp, src, ds, it] = await Promise.all([
      api.adminListSpaces(),
      api.adminListSources(),
      api.adminListDocuments(spaceKey),
      api.adminListItems({ space: spaceKey }),
    ]);
    setSpaces(sp);
    setSources(src);
    setDocs(ds);
    setItems(it);
    if (!sp.some((s) => s.key === spaceKey) && sp[0]) setSpaceKey(sp[0].key);
  }

  useEffect(() => {
    void load().catch((e) =>
      toast.error("Failed to load KB admin data", {
        description: (e as Error).message,
      })
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.is_admin, spaceKey]);

  async function seedSpaces() {
    setBusy(true);
    try {
      for (const [key, name] of DEFAULT_SPACES) {
        await api.adminCreateSpace({ key, name });
      }
      await load();
      toast.success("Default spaces ready");
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function uploadDoc() {
    if (!file) return;
    setBusy(true);
    try {
      const doc = await api.adminUploadDocument(
        spaceKey,
        file,
        undefined,
        undefined,
        parseTags(documentTags),
        createEmbeddings
      );
      await api.adminProcessDocument(doc.id);
      setFile(null);
      await load();
      toast.success("Document uploaded", {
        description: "Processing has been queued.",
      });
    } catch (e) {
      toast.error("Upload failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  function setSelectedFolderFiles(files: FolderUploadFile[], hadInputFiles: boolean) {
    const selected = files
      .filter(({ file }) => isSupportedDocumentFile(file))
      .sort((a, b) => a.path.localeCompare(b.path));
    setFolderFiles(selected);
    if (hadInputFiles && selected.length === 0) {
      toast.warning("No supported documents found", {
        description: `Supported: ${SUPPORTED_KB_ACCEPT}`,
      });
    }
  }

  function chooseFolderFromInput(files: FileList | null) {
    setSelectedFolderFiles(
      Array.from(files || []).map((selectedFile) => ({
        file: selectedFile,
        path: filePath(selectedFile),
      })),
      Boolean(files && files.length > 0)
    );
  }

  async function chooseFolder() {
    const picker = (window as BrowserWindowWithDirectoryPicker).showDirectoryPicker;
    if (!picker) {
      folderInputRef.current?.click();
      return;
    }
    try {
      const root = await picker.call(window);
      const files = await collectDirectoryFiles(root);
      setSelectedFolderFiles(files, true);
    } catch (e) {
      if ((e as DOMException).name === "AbortError") return;
      toast.error("Folder selection failed", {
        description: (e as Error).message,
      });
    }
  }

  async function uploadFolder() {
    if (folderFiles.length === 0) return;
    setBusy(true);
    let uploaded = 0;
    const failures: string[] = [];
    const tags = parseTags(documentTags);
    try {
      for (const nextFile of folderFiles) {
        try {
          const doc = await api.adminUploadDocument(
            spaceKey,
            nextFile.file,
            undefined,
            nextFile.path,
            tags,
            createEmbeddings
          );
          await api.adminProcessDocument(doc.id);
          uploaded += 1;
        } catch (e) {
          failures.push(`${nextFile.path}: ${(e as Error).message}`);
        }
      }
      if (failures.length === 0) {
        setFolderFiles([]);
      }
      await load();
      if (failures.length > 0) {
        toast.error("Folder upload finished with errors", {
          description: `${uploaded} queued, ${failures.length} failed. ${failures[0]}`,
        });
      } else {
        toast.success("Folder uploaded", {
          description: `${uploaded} documents queued for processing.`,
        });
      }
    } finally {
      setBusy(false);
    }
  }

  async function createSource() {
    if (!sourceName.trim() || !sourceUrl.trim()) return;
    setBusy(true);
    try {
      await api.adminCreateSource({
        space_key: spaceKey,
        key: sourceName,
        name: sourceName,
        source_type: "allowlist_url",
        base_url: sourceUrl,
        allowed_use: { store_text: true },
      });
      setSourceName("");
      setSourceUrl("");
      await load();
      toast.success("Source created");
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function addManualItem() {
    if (!manualQuestion.trim()) return;
    setBusy(true);
    try {
      await api.adminCreateItem({
        space_key: spaceKey,
        item_type: "question",
        category: inferCategory(spaceKey),
        title: manualQuestion.slice(0, 120),
        question: manualQuestion,
        answer_outline:
          "A strong answer should cover approach, trade-offs, edge cases, and level-appropriate depth.",
        difficulty: 3,
        tags: [spaceKey],
      });
      setManualQuestion("");
      await load();
      toast.success("Item added");
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  if (!user?.is_admin) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-muted-foreground">
          Admin access is required.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Common KB Admin"
        description="Upload prepared interview documents, register allowlisted sources, and review public KB items."
        actions={
          <>
            <Button variant="outline" onClick={seedSpaces} disabled={busy}>
              <Database className="h-4 w-4" /> Seed spaces
            </Button>
            <Button asChild variant="outline">
              <Link to="/admin/kb/documents">
                <FileText className="h-4 w-4" /> Documents
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/admin/kb/items">
                <ListChecks className="h-4 w-4" /> Items
              </Link>
            </Button>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Space / KB set</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Label>Target space</Label>
            <Select value={spaceKey} onValueChange={setSpaceKey}>
              <SelectTrigger>
                <SelectValue placeholder="Pick a space" />
              </SelectTrigger>
              <SelectContent>
                {spaces.map((s) => (
                  <SelectItem key={s.id} value={s.key}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex flex-wrap gap-2">
              {spaces.map((s) => (
                <Badge key={s.id} variant={s.key === spaceKey ? "default" : "outline"}>
                  {s.key}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Upload Prepared Documents</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Label>Document tags</Label>
              <Input
                value={documentTags}
                onChange={(e) => setDocumentTags(e.target.value)}
                placeholder="meta, graph, python, staff"
              />
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  checked={createEmbeddings}
                  onChange={(e) => setCreateEmbeddings(e.target.checked)}
                />
                Create vector embeddings for mentor/interviewer retrieval
              </label>
              <Label>Single file</Label>
              <Input
                type="file"
                accept={SUPPORTED_KB_ACCEPT}
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
              <Button onClick={uploadDoc} disabled={!file || busy}>
                <FileUp className="h-4 w-4" /> Upload and process
              </Button>
              <div className="border-t pt-3 space-y-3">
                <Label>Folder</Label>
                <Input
                  ref={folderInputRef}
                  type="file"
                  accept={SUPPORTED_KB_ACCEPT}
                  multiple
                  className="hidden"
                  {...DIRECTORY_INPUT_PROPS}
                  onChange={(e) => chooseFolderFromInput(e.target.files)}
                />
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void chooseFolder()}
                >
                  <FolderOpen className="h-4 w-4" /> Choose folder
                </Button>
                {folderFiles.length > 0 && (
                  <div className="rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground">
                    <div className="font-medium text-foreground">
                      {folderFiles.length} supported document
                      {folderFiles.length === 1 ? "" : "s"} selected
                    </div>
                    <div className="mt-1 space-y-0.5">
                      {folderFiles.slice(0, 4).map((f) => (
                        <div key={f.path} className="truncate">
                          {f.path}
                        </div>
                      ))}
                      {folderFiles.length > 4 && (
                        <div>{folderFiles.length - 4} more...</div>
                      )}
                    </div>
                  </div>
                )}
                <Button
                  onClick={uploadFolder}
                  disabled={folderFiles.length === 0 || busy}
                  variant="outline"
                >
                  <FileUp className="h-4 w-4" /> Upload folder
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Allowlisted Source</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Label>Name</Label>
              <Input value={sourceName} onChange={(e) => setSourceName(e.target.value)} />
              <Label>URL</Label>
              <Input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
              <Button onClick={createSource} disabled={busy}>
                <Play className="h-4 w-4" /> Add source
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Manual Item</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            rows={3}
            placeholder="Add a public interview question or topic..."
            value={manualQuestion}
            onChange={(e) => setManualQuestion(e.target.value)}
          />
          <Button onClick={addManualItem} disabled={busy || !manualQuestion.trim()}>
            <Tags className="h-4 w-4" /> Add item
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-base">Recent Documents</CardTitle>
              <Button asChild size="sm" variant="outline">
                <Link to="/admin/kb/documents">View all</Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {docs.slice(0, 8).map((d) => (
              <div key={d.id} className="flex items-center justify-between rounded-md border p-3">
                <div className="min-w-0">
                  <div className="font-medium">{d.title}</div>
                  <div className="text-xs text-muted-foreground">{d.filename}</div>
                  {d.tags.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {d.tags.slice(0, 8).map((tag) => (
                        <Link key={tag} to={`/admin/kb/items?tag=${encodeURIComponent(tag)}`}>
                          <Badge variant="muted" className="hover:bg-accent">
                            {tag}
                          </Badge>
                        </Link>
                      ))}
                      {d.tags.length > 8 && <Badge variant="outline">+{d.tags.length - 8}</Badge>}
                    </div>
                  )}
                  <div className="mt-2">
                    <Badge variant={d.create_embeddings ? "outline" : "muted"}>
                      {d.create_embeddings ? "Embeddings enabled" : "No embeddings"}
                    </Badge>
                  </div>
                </div>
                <StatusPill status={d.status} />
              </div>
            ))}
            {docs.length === 0 && <EmptyLine text="No documents in this space." />}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Sources</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {sourceForSpace.map((s) => (
              <div key={s.id} className="rounded-md border p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-muted-foreground truncate">{s.base_url}</div>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => api.adminRefreshSource(s.id)}>
                    <RefreshCw className="h-4 w-4" /> Refresh
                  </Button>
                </div>
              </div>
            ))}
            {sourceForSpace.length === 0 && <EmptyLine text="No sources in this space." />}
          </CardContent>
        </Card>
      </div>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-base">Recent Items</CardTitle>
              <Button asChild size="sm" variant="outline">
                <Link to="/admin/kb/items">View all</Link>
              </Button>
            </div>
          </CardHeader>
        <CardContent className="space-y-2">
          {items.slice(0, 12).map((it) => (
            <div key={it.id} className="rounded-md border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{it.category}</Badge>
                <Badge variant="muted">{it.item_type}</Badge>
                {it.company && <Badge variant="muted">{it.company}</Badge>}
                {it.language && <Badge variant="muted">{it.language}</Badge>}
                {it.tags.slice(0, 6).map((tag) => (
                  <Link key={tag} to={`/admin/kb/items?tag=${encodeURIComponent(tag)}`}>
                    <Badge variant="muted" className="hover:bg-accent">
                      {tag}
                    </Badge>
                  </Link>
                ))}
              </div>
              <div className="mt-2 font-medium">{it.title}</div>
              {it.question && <div className="mt-1 text-sm text-muted-foreground">{it.question}</div>}
            </div>
          ))}
          {items.length === 0 && <EmptyLine text="No items extracted yet." />}
        </CardContent>
      </Card>
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <div className="py-4 text-sm text-muted-foreground">{text}</div>;
}

function inferCategory(spaceKey: string): string {
  if (spaceKey === "leetcode") return "algorithms";
  if (spaceKey === "company_experience") return "company_experience";
  return spaceKey;
}

function filePath(file: File): string {
  return file.webkitRelativePath || file.name;
}

function isSupportedDocumentFile(file: File): boolean {
  const name = file.name.toLowerCase();
  if (name === ".ds_store") return false;
  const dot = name.lastIndexOf(".");
  if (dot < 0) return false;
  return SUPPORTED_KB_EXTENSIONS.has(name.slice(dot));
}

function parseTags(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(/[\n,]/)
    .map((tag) => tag.trim())
    .filter((tag) => {
      const key = tag.toLowerCase();
      if (!tag || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 20);
}

async function collectDirectoryFiles(
  directory: BrowserDirectoryHandle,
  prefix = ""
): Promise<FolderUploadFile[]> {
  const files: FolderUploadFile[] = [];
  for await (const handle of directory.values()) {
    const path = `${prefix}${handle.name}`;
    if (handle.kind === "file") {
      files.push({ file: await handle.getFile(), path });
    } else {
      files.push(...await collectDirectoryFiles(handle, `${path}/`));
    }
  }
  return files;
}
