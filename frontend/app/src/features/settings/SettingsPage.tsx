import {
  ChevronRight,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  LogOut,
  Monitor,
  Moon,
  Palette,
  Plus,
  ShieldCheck,
  Sun,
  Trash2,
  User as UserIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ApiKey, api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState } from "../../components/common/EmptyState";
import { PageHeader } from "../../components/common/PageHeader";
import { useTheme } from "../../components/theme/ThemeProvider";
import { Avatar, AvatarFallback } from "../../components/ui/avatar";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
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
import { Separator } from "../../components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";
import { cn } from "../../lib/cn";

type SectionId = "profile" | "keys" | "appearance" | "data" | "account";

const SECTIONS: { id: SectionId; label: string; icon: React.ElementType }[] = [
  { id: "profile", label: "Profile", icon: UserIcon },
  { id: "keys", label: "API keys", icon: KeyRound },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "data", label: "Data & privacy", icon: ShieldCheck },
  { id: "account", label: "Account", icon: LogOut },
];

export function SettingsPage() {
  const [section, setSection] = useState<SectionId>("profile");

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Manage your profile, providers, theme, and data."
      />

      <div className="grid gap-6 md:grid-cols-[220px_1fr]">
        <SectionNav active={section} onChange={setSection} />
        <div className="min-w-0 space-y-4">
          {section === "profile" && <ProfileSection />}
          {section === "keys" && <ApiKeysSection />}
          {section === "appearance" && <AppearanceSection />}
          {section === "data" && <DataSection />}
          {section === "account" && <AccountSection />}
        </div>
      </div>
    </div>
  );
}

function SectionNav({
  active,
  onChange,
}: {
  active: SectionId;
  onChange: (id: SectionId) => void;
}) {
  return (
    <nav className="flex md:flex-col gap-1 overflow-x-auto md:overflow-visible -mx-1 md:mx-0 px-1 md:px-0">
      {SECTIONS.map((s) => {
        const Icon = s.icon;
        const isActive = s.id === active;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onChange(s.id)}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap shrink-0",
              isActive
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-accent hover:text-foreground"
            )}
          >
            <Icon className="h-4 w-4" />
            {s.label}
            <ChevronRight
              className={cn(
                "ml-auto h-4 w-4 hidden md:block transition-opacity",
                isActive ? "opacity-100" : "opacity-0"
              )}
            />
          </button>
        );
      })}
    </nav>
  );
}

// ---------- Profile ----------

function ProfileSection() {
  const { user } = useAuth();
  if (!user) return null;
  const initials = (user.display_name || user.email)
    .split(/\s+/)
    .map((s) => s[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profile</CardTitle>
        <CardDescription>
          How you appear in the app. Editing is coming soon.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex items-center gap-4">
          <Avatar className="h-14 w-14">
            <AvatarFallback className="bg-primary/10 text-primary text-base">
              {initials}
            </AvatarFallback>
          </Avatar>
          <div className="space-y-1">
            <div className="text-base font-semibold">{user.display_name}</div>
            <div className="text-sm text-muted-foreground">{user.email}</div>
            <Badge variant="muted" className="capitalize">
              {user.tier || "free"} tier
            </Badge>
          </div>
        </div>

        <Separator />

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label>Display name</Label>
            <Input value={user.display_name} disabled />
          </div>
          <div className="space-y-2">
            <Label>Email</Label>
            <Input value={user.email} disabled />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------- API keys ----------

const PROVIDERS = ["openai", "anthropic", "ollama", "openrouter", "together"];

function ApiKeysSection() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [adding, setAdding] = useState(false);
  const [provider, setProvider] = useState("openai");
  const [label, setLabel] = useState("");
  const [plaintext, setPlaintext] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setKeys(await api.listApiKeys());
    } catch (e) {
      toast.error("Failed to load keys", {
        description: (e as Error).message,
      });
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.addApiKey(provider, label, plaintext);
      setLabel("");
      setPlaintext("");
      setAdding(false);
      toast.success("Key added", { description: "Encrypted and stored." });
      await load();
    } catch (ex) {
      toast.error("Failed", { description: (ex as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this API key?")) return;
    try {
      await api.deleteApiKey(id);
      toast.success("Key deleted");
      await load();
    } catch (e) {
      toast.error("Failed", { description: (e as Error).message });
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div className="space-y-1">
          <CardTitle>API keys</CardTitle>
          <CardDescription>
            Bring your own provider. Keys are encrypted at rest and never
            returned in plaintext.
          </CardDescription>
        </div>
        {!adding ? (
          <Button onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" /> Add key
          </Button>
        ) : null}
      </CardHeader>

      {adding ? (
        <CardContent className="border-y bg-muted/30 py-5">
          <form onSubmit={add} className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Provider</Label>
              <Select value={provider} onValueChange={setProvider}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDERS.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="label">Label</Label>
              <Input
                id="label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Personal, Work..."
              />
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="key">API key</Label>
              <div className="relative">
                <Input
                  id="key"
                  type={showSecret ? "text" : "password"}
                  value={plaintext}
                  onChange={(e) => setPlaintext(e.target.value)}
                  placeholder="sk-..."
                  className="pr-10 font-mono"
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setShowSecret((v) => !v)}
                  aria-label={showSecret ? "Hide" : "Show"}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {showSecret ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>
            <div className="sm:col-span-2 flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setAdding(false);
                  setPlaintext("");
                  setLabel("");
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={busy || !plaintext}>
                {busy ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Adding...
                  </>
                ) : (
                  "Save key"
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      ) : null}

      <CardContent className="p-0">
        {keys.length === 0 ? (
          <EmptyState
            icon={KeyRound}
            title="No API keys yet"
            description="Add a provider key to start using your own model."
            action={
              !adding ? (
                <Button onClick={() => setAdding(true)}>
                  <Plus className="h-4 w-4" /> Add key
                </Button>
              ) : null
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Label</TableHead>
                <TableHead>Added</TableHead>
                <TableHead className="text-right" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((k) => (
                <TableRow key={k.id}>
                  <TableCell>
                    <Badge variant="muted" className="capitalize">
                      {k.provider}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {k.label || (
                      <span className="text-muted-foreground italic">
                        (none)
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(k.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => remove(k.id)}
                    >
                      <Trash2 className="h-4 w-4" /> Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ---------- Appearance ----------

function AppearanceSection() {
  const { theme, setTheme } = useTheme();
  const opts: { value: typeof theme; label: string; icon: React.ElementType }[] = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>
          Customize how Open Interview looks on your device.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Label className="text-xs uppercase tracking-wide text-muted-foreground">
          Theme
        </Label>
        <div className="grid gap-3 sm:grid-cols-3">
          {opts.map((o) => {
            const Icon = o.icon;
            const isActive = theme === o.value;
            return (
              <button
                key={o.value}
                type="button"
                onClick={() => setTheme(o.value)}
                className={cn(
                  "flex flex-col items-start rounded-xl border p-4 gap-2 text-left transition-colors",
                  isActive
                    ? "border-primary ring-2 ring-primary/40 bg-primary/5"
                    : "hover:border-foreground/30"
                )}
              >
                <Icon className="h-5 w-5 text-primary" />
                <span className="text-sm font-medium">{o.label}</span>
                <span className="text-xs text-muted-foreground">
                  {o.value === "system"
                    ? "Match OS preference"
                    : `${o.label} mode`}
                </span>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------- Data & privacy ----------

function DataSection() {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Export data</CardTitle>
          <CardDescription>
            Download a zip of your projects, resume, QA sets, sessions, and
            evaluations.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" disabled>
            Export everything (coming soon)
          </Button>
        </CardContent>
      </Card>
      <Card className="border-destructive/30">
        <CardHeader>
          <CardTitle className="text-destructive">Wipe all data</CardTitle>
          <CardDescription>
            Permanently delete every project, session, memory, and resume. This
            cannot be undone.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" disabled>
            <Trash2 className="h-4 w-4" /> Wipe my data (coming soon)
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------- Account ----------

function AccountSection() {
  const { logout } = useAuth();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Account</CardTitle>
        <CardDescription>
          Manage your session. Account deletion is coming soon.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-3">
          <Button variant="outline" onClick={logout}>
            <LogOut className="h-4 w-4" /> Sign out
          </Button>
          <Button variant="destructive" disabled>
            <Trash2 className="h-4 w-4" /> Delete account (coming soon)
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
