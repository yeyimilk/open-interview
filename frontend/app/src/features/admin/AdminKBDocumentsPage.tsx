import { ArrowLeft, FileText, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { CommonKBDocumentOut, CommonKBSpaceOut, api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { PageHeader } from "../../components/common/PageHeader";
import { StatusPill } from "../../components/common/StatusPill";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Label } from "../../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";

const ALL = "__all__";

export function AdminKBDocumentsPage() {
  const { user } = useAuth();
  const [spaces, setSpaces] = useState<CommonKBSpaceOut[]>([]);
  const [docs, setDocs] = useState<CommonKBDocumentOut[]>([]);
  const [space, setSpace] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function loadDocuments(nextSpace = space, nextStatus = status) {
    if (!user?.is_admin) return;
    setLoading(true);
    try {
      const [sp, ds] = await Promise.all([
        api.adminListSpaces(),
        api.adminListDocuments({
          space: nextSpace || undefined,
          status: nextStatus || undefined,
          limit: 2000,
        }),
      ]);
      setSpaces(sp);
      setDocs(ds);
    } catch (e) {
      toast.error("Failed to load documents", {
        description: (e as Error).message,
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.is_admin]);

  async function deleteDocument(doc: CommonKBDocumentOut) {
    const confirmed = window.confirm(
      `Delete "${doc.title}" and all extracted KB items from this document?`
    );
    if (!confirmed) return;
    setDeletingId(doc.id);
    try {
      await api.adminDeleteDocument(doc.id);
      setDocs((prev) => prev.filter((d) => d.id !== doc.id));
      toast.success("Document deleted");
    } catch (e) {
      toast.error("Delete failed", { description: (e as Error).message });
    } finally {
      setDeletingId(null);
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
        title="KB Documents"
        description="Review uploaded and crawled source files, processing status, tags, and embedding policy."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/admin/kb">
                <ArrowLeft className="h-4 w-4" /> Upload
              </Link>
            </Button>
            <Button variant="outline" onClick={() => void loadDocuments()} disabled={loading}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="grid gap-3 p-4 md:grid-cols-[220px_180px_auto]">
          <div className="space-y-2">
            <Label>Space</Label>
            <Select
              value={space || ALL}
              onValueChange={(value) => setSpace(value === ALL ? "" : value)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All spaces</SelectItem>
                {spaces.map((sp) => (
                  <SelectItem key={sp.id} value={sp.key}>
                    {sp.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Status</Label>
            <Select
              value={status || ALL}
              onValueChange={(value) => setStatus(value === ALL ? "" : value)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All statuses</SelectItem>
                <SelectItem value="uploaded">Uploaded</SelectItem>
                <SelectItem value="processing">Processing</SelectItem>
                <SelectItem value="processed">Processed</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-end">
            <Button onClick={() => void loadDocuments()} disabled={loading}>
              Apply filters
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Document</TableHead>
                <TableHead>Tags</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Embedding</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.map((doc) => (
                <TableRow key={doc.id}>
                  <TableCell>
                    <div className="flex items-start gap-2">
                      <FileText className="mt-0.5 h-4 w-4 text-muted-foreground" />
                      <div className="min-w-0">
                        <div className="font-medium">{doc.title}</div>
                        <div className="truncate text-xs text-muted-foreground">
                          {doc.filename || doc.canonical_url || doc.blob_path}
                        </div>
                        {doc.error && (
                          <div className="mt-1 line-clamp-2 text-xs text-destructive">
                            {doc.error}
                          </div>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <TagList tags={doc.tags} />
                  </TableCell>
                  <TableCell>
                    <StatusPill status={doc.status} />
                  </TableCell>
                  <TableCell>
                    <Badge variant={doc.create_embeddings ? "outline" : "muted"}>
                      {doc.create_embeddings ? "Enabled" : "Skipped"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDate(doc.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={deletingId === doc.id}
                      onClick={() => void deleteDocument(doc)}
                    >
                      <Trash2 className="h-4 w-4" /> Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {docs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                    No documents match the current filters.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function TagList({ tags }: { tags: string[] }) {
  if (tags.length === 0) {
    return <span className="text-xs text-muted-foreground">No tags</span>;
  }
  return (
    <div className="flex max-w-sm flex-wrap gap-1">
      {tags.slice(0, 8).map((tag) => (
        <Badge key={tag} variant="muted">
          {tag}
        </Badge>
      ))}
      {tags.length > 8 && <Badge variant="outline">+{tags.length - 8}</Badge>}
    </div>
  );
}

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}
