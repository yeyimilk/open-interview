import { ArrowLeft, Filter, RefreshCw, Tags } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { CommonKBItemOut, CommonKBSpaceOut, api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { PageHeader } from "../../components/common/PageHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
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

interface ItemFilters {
  space: string;
  tag: string;
  category: string;
  company: string;
  language: string;
}

const EMPTY_FILTERS: ItemFilters = {
  space: "",
  tag: "",
  category: "",
  company: "",
  language: "",
};

export function AdminKBItemsPage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [spaces, setSpaces] = useState<CommonKBSpaceOut[]>([]);
  const [items, setItems] = useState<CommonKBItemOut[]>([]);
  const [filters, setFilters] = useState<ItemFilters>(() => filtersFromSearch(searchParams));
  const [loading, setLoading] = useState(false);

  async function loadItems(nextFilters = filters) {
    if (!user?.is_admin) return;
    setLoading(true);
    try {
      const [sp, rows] = await Promise.all([
        api.adminListSpaces(),
        api.adminListItems({
          space: nextFilters.space || undefined,
          tag: nextFilters.tag || undefined,
          category: nextFilters.category || undefined,
          company: nextFilters.company || undefined,
          language: nextFilters.language || undefined,
          limit: 2000,
        }),
      ]);
      setSpaces(sp);
      setItems(rows);
    } catch (e) {
      toast.error("Failed to load items", {
        description: (e as Error).message,
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.is_admin]);

  function updateFilter<K extends keyof ItemFilters>(key: K, value: ItemFilters[K]) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function applyTag(tag: string) {
    const next = { ...filters, tag };
    setFilters(next);
    syncSearchParams(next, setSearchParams);
    void loadItems(next);
  }

  function applyFilters() {
    syncSearchParams(filters, setSearchParams);
    void loadItems(filters);
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    setSearchParams({});
    void loadItems(EMPTY_FILTERS);
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
        title="KB Items"
        description="Review normalized interview questions, topics, company reports, and searchable tags."
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/admin/kb">
                <ArrowLeft className="h-4 w-4" /> Upload
              </Link>
            </Button>
            <Button variant="outline" onClick={() => void loadItems()} disabled={loading}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="grid gap-3 p-4 lg:grid-cols-[180px_180px_180px_1fr_1fr_auto_auto]">
          <div className="space-y-2">
            <Label>Space</Label>
            <Select
              value={filters.space || ALL}
              onValueChange={(value) => updateFilter("space", value === ALL ? "" : value)}
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
            <Label>Category</Label>
            <Input
              value={filters.category}
              onChange={(e) => updateFilter("category", e.target.value)}
              placeholder="system_design"
            />
          </div>
          <div className="space-y-2">
            <Label>Tag</Label>
            <Input
              value={filters.tag}
              onChange={(e) => updateFilter("tag", e.target.value)}
              placeholder="graph"
            />
          </div>
          <div className="space-y-2">
            <Label>Company</Label>
            <Input
              value={filters.company}
              onChange={(e) => updateFilter("company", e.target.value)}
              placeholder="Meta"
            />
          </div>
          <div className="space-y-2">
            <Label>Language</Label>
            <Input
              value={filters.language}
              onChange={(e) => updateFilter("language", e.target.value)}
              placeholder="Python"
            />
          </div>
          <div className="flex items-end">
            <Button onClick={applyFilters} disabled={loading}>
              <Filter className="h-4 w-4" /> Apply
            </Button>
          </div>
          <div className="flex items-end">
            <Button variant="outline" onClick={clearFilters} disabled={loading}>
              Clear
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Item</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Tags</TableHead>
                <TableHead>Company</TableHead>
                <TableHead>Language</TableHead>
                <TableHead>Difficulty</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="max-w-xl">
                    <div className="font-medium">{item.title}</div>
                    {item.question && (
                      <div className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                        {item.question}
                      </div>
                    )}
                    {!item.question && item.content && (
                      <div className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                        {item.content}
                      </div>
                    )}
                    <Badge variant="muted" className="mt-2">
                      {item.item_type}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{item.category}</Badge>
                  </TableCell>
                  <TableCell>
                    <TagList tags={item.tags} onPick={applyTag} />
                  </TableCell>
                  <TableCell>{item.company || <MutedDash />}</TableCell>
                  <TableCell>{item.language || <MutedDash />}</TableCell>
                  <TableCell>{item.difficulty}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDate(item.created_at)}
                  </TableCell>
                </TableRow>
              ))}
              {items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-sm text-muted-foreground">
                    No items match the current filters.
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

function TagList({ tags, onPick }: { tags: string[]; onPick: (tag: string) => void }) {
  if (tags.length === 0) {
    return <span className="text-xs text-muted-foreground">No tags</span>;
  }
  return (
    <div className="flex max-w-sm flex-wrap gap-1">
      {tags.slice(0, 10).map((tag) => (
        <button key={tag} type="button" onClick={() => onPick(tag)}>
          <Badge variant="muted" className="hover:bg-accent">
            <Tags className="h-3 w-3" /> {tag}
          </Badge>
        </button>
      ))}
      {tags.length > 10 && <Badge variant="outline">+{tags.length - 10}</Badge>}
    </div>
  );
}

function MutedDash() {
  return <span className="text-muted-foreground">-</span>;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString();
}

function filtersFromSearch(searchParams: URLSearchParams): ItemFilters {
  return {
    space: searchParams.get("space") || "",
    tag: searchParams.get("tag") || "",
    category: searchParams.get("category") || "",
    company: searchParams.get("company") || "",
    language: searchParams.get("language") || "",
  };
}

function syncSearchParams(
  filters: ItemFilters,
  setSearchParams: (nextInit: URLSearchParams) => void
) {
  const next = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) next.set(key, value);
  }
  setSearchParams(next);
}
