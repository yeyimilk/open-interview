import {
  Brain,
  Check,
  ChevronRight,
  CircleAlert,
  Download,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  LogOut,
  MessageSquare,
  Monitor,
  Moon,
  Palette,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Sun,
  Trash2,
  Unlink,
  User as UserIcon,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ApiKey,
  MessagingFilters,
  MessagingGroup,
  MessagingLinkOut,
  MessagingLinkStatus,
  MessagingPairSession,
  MessagingPluginInfo,
  ModelPreferenceBody,
  ModelPreferenceOut,
  ModelRole,
  ProviderModel,
  api,
} from "../../api/client";
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

type SectionId =
  | "profile"
  | "keys"
  | "models"
  | "messaging"
  | "appearance"
  | "data"
  | "account";

const SECTIONS: { id: SectionId; label: string; icon: React.ElementType }[] = [
  { id: "profile", label: "Profile", icon: UserIcon },
  { id: "keys", label: "API keys", icon: KeyRound },
  { id: "models", label: "Models", icon: Brain },
  { id: "messaging", label: "Messaging", icon: MessageSquare },
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
          {section === "models" && <ModelProvidersSection />}
          {section === "messaging" && <MessagingSection />}
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

// ---------- Model providers ----------

type RoleMeta = {
  role: ModelRole;
  title: string;
  description: string;
  fallbackEndpoint: string;
  fallbackProvider: string;
  // returns true for models suitable for this role on the given provider
  filter: (id: string, provider: string) => boolean;
  // suggested default model id per provider (best match for the role)
  defaultModel: (provider: string) => string | null;
};

function isLLMChatModel(id: string): boolean {
  const i = id.toLowerCase();
  if (
    i.includes("embed") ||
    i.includes("whisper") ||
    i.includes("transcribe") ||
    i.includes("tts") ||
    i.includes("audio") ||
    i.includes("image") ||
    i.includes("dall-e") ||
    i.includes("vision") ||
    i.includes("moderation") ||
    i.includes("realtime") ||
    i.includes("davinci") ||
    i.includes("babbage") ||
    i.includes("instruct") ||
    i.includes("guard") ||
    i.includes("rerank")
  ) {
    return false;
  }
  return /^(gpt-|o1|o3|o4|chatgpt|claude|gemini|llama|mixtral|mistral|qwen|deepseek|grok|command|nova|sonar|phi|yi-)/.test(
    i
  );
}

const ROLE_META: RoleMeta[] = [
  {
    role: "chat",
    title: "Chat / LLM",
    description:
      "Used by the mentor, mock interviewer and project explainer.",
    fallbackEndpoint: "https://api.openai.com/v1",
    fallbackProvider: "openai",
    filter: (id) => isLLMChatModel(id),
    defaultModel: (p) =>
      ({
        openai: "gpt-5",
        anthropic: "claude-3-5-sonnet-latest",
        openrouter: "openai/gpt-4o-mini",
        together: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        fireworks: "accounts/fireworks/models/llama-v3p3-70b-instruct",
        groq: "llama-3.3-70b-versatile",
        deepseek: "deepseek-chat",
        ollama: "llama3.1",
      }[p] ?? null),
  },
  {
    role: "embedding",
    title: "Embeddings",
    description: "Used for project search and long-term memory recall.",
    fallbackEndpoint: "https://api.openai.com/v1",
    fallbackProvider: "openai",
    filter: (id) => /embed|bge|e5/i.test(id),
    defaultModel: (p) =>
      ({
        openai: "text-embedding-3-small",
        together: "BAAI/bge-large-en-v1.5",
        fireworks: "nomic-ai/nomic-embed-text-v1.5",
        ollama: "nomic-embed-text",
      }[p] ?? null),
  },
  {
    role: "transcription",
    title: "Transcription (STT)",
    description: "Used to convert your voice answers into text.",
    fallbackEndpoint: "https://api.openai.com/v1",
    fallbackProvider: "openai",
    filter: (id) =>
      /whisper|transcribe|stt|gpt-4o-(mini-)?transcribe/i.test(id),
    defaultModel: (p) =>
      ({
        openai: "gpt-4o-mini-transcribe",
        groq: "whisper-large-v3",
      }[p] ?? null),
  },
  {
    role: "voice-analysis",
    title: "Voice analysis",
    description:
      "Multimodal model that scores delivery (pace, fillers, clarity).",
    fallbackEndpoint: "https://api.openai.com/v1",
    fallbackProvider: "openai",
    // multimodal chat models that accept audio input
    filter: (id) => /^(gpt-4o(-audio)?|gpt-5|chatgpt-4o)/i.test(id),
    defaultModel: (p) =>
      ({
        openai: "gpt-4o-audio-preview",
      }[p] ?? null),
  },
];

function ModelProvidersSection() {
  const [prefs, setPrefs] = useState<
    Partial<Record<ModelRole, ModelPreferenceOut>>
  >({});
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      const [list, ks] = await Promise.all([
        api.listModelPreferences(),
        api.listApiKeys(),
      ]);
      const map: Partial<Record<ModelRole, ModelPreferenceOut>> = {};
      for (const p of list) map[p.role] = p;
      setPrefs(map);
      setKeys(ks);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Model providers</CardTitle>
        <CardDescription>
          Pick which provider and model to use for each role. Falls back to
          the server default when no override is set. Add an API key first
          under <span className="font-medium">API keys</span>.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {loadErr && (
          <p className="text-sm text-destructive">{loadErr}</p>
        )}
        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : keys.length === 0 ? (
          <EmptyState
            icon={KeyRound}
            title="No API keys yet"
            description="Add at least one provider key on the API keys tab to enable per-role overrides."
          />
        ) : (
          ROLE_META.map((m) => (
            <RoleCard
              key={m.role}
              meta={m}
              keys={keys}
              pref={prefs[m.role] ?? null}
              onChanged={() => void reload()}
            />
          ))
        )}
      </CardContent>
    </Card>
  );
}

function RoleCard({
  meta,
  keys,
  pref,
  onChanged,
}: {
  meta: (typeof ROLE_META)[number];
  keys: ApiKey[];
  pref: ModelPreferenceOut | null;
  onChanged: () => void;
}) {
  const initialProvider =
    pref?.provider ?? keys[0]?.provider ?? meta.fallbackProvider;
  const initialEndpoint =
    pref?.endpoint ?? endpointForProvider(initialProvider, meta.fallbackEndpoint);

  const [provider, setProvider] = useState(initialProvider);
  const [endpoint, setEndpoint] = useState(initialEndpoint);
  const [modelId, setModelId] = useState(pref?.model_id ?? "");
  const [advanced, setAdvanced] = useState(false);
  const [showAllModels, setShowAllModels] = useState(false);
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [discoverErr, setDiscoverErr] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testOk, setTestOk] = useState<boolean | null>(null);
  const [testMsg, setTestMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const providers = useMemo(
    () => Array.from(new Set(keys.map((k) => k.provider))),
    [keys]
  );

  const discover = useCallback(
    async (p: string, e: string) => {
      setDiscovering(true);
      setDiscoverErr(null);
      try {
        const res = await api.listProviderModels(p, e);
        setModels(res.models);
      } catch (err) {
        setDiscoverErr(err instanceof Error ? err.message : String(err));
        setModels([]);
      } finally {
        setDiscovering(false);
      }
    },
    []
  );

  useEffect(() => {
    void discover(provider, endpoint);
  }, [provider, endpoint, discover]);

  // Filtered list (per-role) and pre-selection of a sensible default.
  const filteredModels = useMemo(() => {
    if (showAllModels) return models;
    const f = models.filter((m) => meta.filter(m.id, provider));
    return f.length > 0 ? f : models;
  }, [models, meta, provider, showAllModels]);

  useEffect(() => {
    if (modelId || filteredModels.length === 0) return;
    const suggested = meta.defaultModel(provider);
    const ids = filteredModels.map((m) => m.id);
    const pick =
      (suggested && ids.find((id) => id === suggested)) ??
      (suggested && ids.find((id) => id.includes(suggested))) ??
      ids[0];
    if (pick) setModelId(pick);
  }, [filteredModels, meta, provider, modelId]);

  // When provider changes via the dropdown, snap to its conventional
  // endpoint (unless the user is editing the endpoint manually) and
  // clear the previous model pick so we re-suggest from the new catalog.
  function onProviderChange(p: string) {
    setProvider(p);
    if (!advanced) {
      setEndpoint(endpointForProvider(p, meta.fallbackEndpoint));
    }
    setModelId("");
    setTestOk(null);
    setTestMsg(null);
  }

  async function onTest() {
    if (!modelId.trim()) {
      setTestOk(false);
      setTestMsg("pick a model first");
      return;
    }
    setTesting(true);
    setTestOk(null);
    setTestMsg(null);
    try {
      const body: ModelPreferenceBody = {
        provider,
        endpoint,
        model_id: modelId.trim(),
      };
      const res = await api.testModelPreference(meta.role, body);
      setTestOk(res.ok);
      setTestMsg(
        res.ok
          ? `OK — round-trip ${res.latency_ms}ms`
          : (res.error ?? "test failed")
      );
    } catch (e) {
      setTestOk(false);
      setTestMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setTesting(false);
    }
  }

  async function onSave() {
    if (!modelId.trim()) return;
    setSaving(true);
    setError(null);
    try {
      // Block save until a successful test. For transcription the gateway's
      // /test endpoint can only verify the model id appears in the
      // provider's catalogue (no synthetic audio), so a green test there is
      // a weaker guarantee — but we still require it to run.
      if (testOk !== true) {
        await onTest();
        return;
      }
      await api.upsertModelPreference(meta.role, {
        provider,
        endpoint,
        model_id: modelId.trim(),
      });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function onReset() {
    setResetting(true);
    setError(null);
    try {
      await api.deleteModelPreference(meta.role);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="rounded-md border p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-medium">{meta.title}</div>
          <div className="text-xs text-muted-foreground">
            {meta.description}
          </div>
        </div>
        <Badge variant={pref ? "default" : "secondary"}>
          {pref ? "custom" : "default"}
        </Badge>
      </div>

      <div className="grid gap-3 md:grid-cols-2 md:items-start">
        <div className="space-y-1">
          <div className="flex h-5 items-center justify-between">
            <Label>Provider</Label>
          </div>
          <Select value={provider} onValueChange={onProviderChange}>
            <SelectTrigger>
              <SelectValue placeholder="Pick a provider" />
            </SelectTrigger>
            <SelectContent>
              {providers.map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <div className="flex h-5 items-center justify-between">
            <Label className="flex items-center gap-1">
              Model
              {discovering && (
                <Loader2 className="h-3 w-3 animate-spin opacity-60" />
              )}
            </Label>
            {models.length > 0 && (
              <button
                type="button"
                className="text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setShowAllModels((v) => !v)}
              >
                {showAllModels
                  ? `Recommended (${
                      models.filter((m) => meta.filter(m.id, provider)).length
                    })`
                  : `Show all (${models.length})`}
              </button>
            )}
          </div>
          {filteredModels.length > 0 ? (
            <Select value={modelId} onValueChange={setModelId}>
              <SelectTrigger>
                <SelectValue placeholder="Pick a model" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {filteredModels.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Input
              placeholder="e.g. gpt-4o-mini"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
            />
          )}
          {discoverErr && (
            <div className="text-xs text-muted-foreground">
              live discovery failed — type the model id manually.
            </div>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={() => setAdvanced((v) => !v)}
        className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform ${
            advanced ? "rotate-90" : ""
          }`}
        />
        Advanced (custom endpoint / model id)
      </button>
      {advanced && (
        <div className="grid gap-3 md:grid-cols-2 pt-1">
          <div className="space-y-1">
            <Label>Endpoint URL</Label>
            <Input
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="https://…/v1"
            />
          </div>
          <div className="space-y-1">
            <Label>Model ID</Label>
            <Input
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              placeholder="provider/model-name"
            />
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button
          variant="outline"
          size="sm"
          onClick={onTest}
          disabled={testing || saving || !modelId.trim()}
        >
          {testing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : testOk === true ? (
            <Check className="h-4 w-4 text-green-600" />
          ) : testOk === false ? (
            <X className="h-4 w-4 text-destructive" />
          ) : null}
          Test
        </Button>
        <Button
          size="sm"
          onClick={onSave}
          disabled={saving || !modelId.trim() || testOk !== true}
        >
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Check className="h-4 w-4" />
          )}{" "}
          Save
        </Button>
        {pref && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onReset}
            disabled={resetting}
          >
            {resetting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RotateCcw className="h-4 w-4" />
            )}{" "}
            Reset to default
          </Button>
        )}
        {testMsg && (
          <span
            className={`text-xs ${
              testOk ? "text-green-600" : "text-destructive"
            }`}
          >
            {testMsg}
          </span>
        )}
        {error && (
          <span className="text-xs text-destructive">{error}</span>
        )}
      </div>
    </div>
  );
}

function endpointForProvider(provider: string, fallback: string): string {
  switch (provider) {
    case "openai":
      return "https://api.openai.com/v1";
    case "anthropic":
      return "https://api.anthropic.com/v1";
    case "openrouter":
      return "https://openrouter.ai/api/v1";
    case "together":
      return "https://api.together.xyz/v1";
    case "fireworks":
      return "https://api.fireworks.ai/inference/v1";
    case "groq":
      return "https://api.groq.com/openai/v1";
    case "deepseek":
      return "https://api.deepseek.com/v1";
    case "ollama":
      return "http://localhost:11434/v1";
    default:
      return fallback;
  }
}

// ---------- Messaging ----------

function MessagingSection() {
  const [plugins, setPlugins] = useState<MessagingPluginInfo[] | null>(null);
  const [links, setLinks] = useState<MessagingLinkOut[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const [ps, ls] = await Promise.all([
        api.listMessagingPlugins(),
        api.listMessagingLinks(),
      ]);
      setPlugins(ps);
      setLinks(ls);
      setLoadErr(null);
    } catch (e) {
      setLoadErr((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Messaging</CardTitle>
        <CardDescription>
          Connect a messaging app and chat with the mentor and interviewer
          from your phone.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {loadErr && (
          <div className="rounded border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {loadErr}
          </div>
        )}

        <ConnectedLinks
          links={links}
          onUnlinked={() => refresh()}
        />

        <Separator />

        <AvailablePlugins
          plugins={plugins}
          onLinked={() => refresh()}
        />
      </CardContent>
    </Card>
  );
}

function ConnectedLinks({
  links,
  onUnlinked,
}: {
  links: MessagingLinkOut[] | null;
  onUnlinked: () => void;
}) {
  if (links === null) return <div className="text-sm text-muted-foreground">Loading…</div>;
  if (links.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">
        No messaging accounts connected yet.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="text-sm font-medium">Connected accounts</div>
      {links.map((l) => (
        <LinkCard key={l.id} link={l} onUnlinked={onUnlinked} />
      ))}
    </div>
  );
}

function LinkCard({
  link,
  onUnlinked,
}: {
  link: MessagingLinkOut;
  onUnlinked: () => void;
}) {
  const [showFilters, setShowFilters] = useState(false);
  const [status, setStatus] = useState<MessagingLinkStatus | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.getLinkStatus(link.id));
    } catch {
      setStatus({
        id: link.id,
        channel: link.channel,
        state: "unavailable",
        detail: "status check failed",
        last_seen_at: link.last_seen_at,
      });
    }
  }, [link.channel, link.id, link.last_seen_at]);

  useEffect(() => {
    void refreshStatus();
    const id = window.setInterval(() => void refreshStatus(), 10_000);
    return () => window.clearInterval(id);
  }, [refreshStatus]);

  return (
    <div className="rounded-lg border">
      <div className="flex items-center justify-between gap-3 p-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-sm font-medium capitalize">{link.channel}</div>
            <LinkHealthBadge status={status} fallbackLastSeen={link.last_seen_at} />
          </div>
          <div className="font-mono text-xs text-muted-foreground truncate">
            {link.display_name
              ? `+${link.display_name} (${link.external_id})`
              : link.external_id}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {link.channel === "whatsapp" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowFilters((v) => !v)}
            >
              {showFilters ? "Hide" : "Allowed conversations"}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => {
              if (!confirm("Disconnect this account? You'll need to re-pair to use it again.")) return;
              try {
                await api.deleteMessagingLink(link.id);
                toast.success("Account disconnected");
                onUnlinked();
              } catch (e) {
                toast.error("Failed", { description: (e as Error).message });
              }
            }}
          >
            <Unlink className="h-4 w-4 mr-1" />
            Disconnect
          </Button>
        </div>
      </div>
      {showFilters && link.channel === "whatsapp" && (
        <div className="border-t p-3 bg-muted/30">
          <FiltersEditor link={link} />
        </div>
      )}
    </div>
  );
}

function LinkHealthBadge({
  status,
  fallbackLastSeen,
}: {
  status: MessagingLinkStatus | null;
  fallbackLastSeen: string | null;
}) {
  const state = status?.state ?? "unavailable";
  const lastSeen = status?.last_seen_at ?? fallbackLastSeen;
  const title = lastSeen ? `Last activity ${formatAgo(lastSeen)}` : undefined;
  if (!status) {
    return (
      <Badge variant="muted" title={title}>
        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
        Checking
      </Badge>
    );
  }
  if (state === "connected") {
    return (
      <Badge variant="success" title={title}>
        <Wifi className="mr-1 h-3 w-3" />
        Connected
      </Badge>
    );
  }
  if (state === "re_pair_needed") {
    return (
      <Badge variant="warning" title={status.detail ?? title}>
        <WifiOff className="mr-1 h-3 w-3" />
        Re-pair needed
      </Badge>
    );
  }
  return (
    <Badge variant="muted" title={status.detail ?? title}>
      <CircleAlert className="mr-1 h-3 w-3" />
      Unavailable
    </Badge>
  );
}

function formatAgo(value: string): string {
  const ts = new Date(value).getTime();
  if (!Number.isFinite(ts)) return "unknown";
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function FiltersEditor({ link }: { link: MessagingLinkOut }) {
  const [filters, setFilters] = useState<MessagingFilters | null>(null);
  const [groups, setGroups] = useState<MessagingGroup[] | null>(null);
  const [phoneInput, setPhoneInput] = useState("");
  const [inviteInput, setInviteInput] = useState("");
  const [groupSearch, setGroupSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [savingMode, setSavingMode] = useState(false);

  // initial load
  useEffect(() => {
    void (async () => {
      try {
        setFilters(await api.getLinkFilters(link.id));
      } catch (e) {
        toast.error("Failed to load filters", { description: (e as Error).message });
      }
    })();
  }, [link.id]);

  function setMode(mode: MessagingFilters["mode"]) {
    if (!filters) return;
    setFilters({ ...filters, mode });
  }

  function addRule(kind: "phone" | "group", value: string, label?: string) {
    if (!filters) return;
    const exists = filters.rules.some(
      (r) => r.kind === kind && r.value === value
    );
    if (exists) return;
    setFilters({
      ...filters,
      rules: [...filters.rules, { kind, value, label: label ?? null }],
    });
  }

  function removeRule(idx: number) {
    if (!filters) return;
    const next = filters.rules.slice();
    next.splice(idx, 1);
    setFilters({ ...filters, rules: next });
  }

  async function loadGroups() {
    setBusy(true);
    try {
      const list = await api.listLinkGroups(link.id);
      setGroups(list);
    } catch (e) {
      toast.error("Couldn't load groups", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function resolveInvite() {
    if (!inviteInput.trim()) return;
    setBusy(true);
    try {
      const g = await api.resolveLinkInvite(link.id, inviteInput.trim());
      addRule("group", g.jid, g.subject);
      setInviteInput("");
      toast.success(`Added ${g.subject}`);
    } catch (e) {
      toast.error("Invite link invalid", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!filters) return;
    setSavingMode(true);
    try {
      const saved = await api.putLinkFilters(link.id, filters);
      setFilters(saved);
      toast.success("Filters saved");
    } catch (e) {
      toast.error("Save failed", { description: (e as Error).message });
    } finally {
      setSavingMode(false);
    }
  }

  const selectedGroupIds = useMemo(
    () =>
      new Set(
        (filters?.rules ?? [])
          .filter((rule) => rule.kind === "group")
          .map((rule) => rule.value)
      ),
    [filters?.rules]
  );
  const filteredGroups = useMemo(() => {
    if (!groups) return [];
    const q = groupSearch.trim().toLowerCase();
    if (!q) return groups;
    return groups.filter((group) =>
      `${group.subject} ${group.jid}`.toLowerCase().includes(q)
    );
  }, [groups, groupSearch]);

  if (!filters) return <div className="text-xs text-muted-foreground">Loading…</div>;

  const showRulesEditor =
    filters.mode === "allowlist" || filters.mode === "denylist";
  const selectedVisibleCount = filteredGroups.filter((group) =>
    selectedGroupIds.has(group.jid)
  ).length;

  function toggleGroup(group: MessagingGroup) {
    if (!filters) return;
    if (selectedGroupIds.has(group.jid)) {
      setFilters({
        ...filters,
        rules: filters.rules.filter(
          (rule) => !(rule.kind === "group" && rule.value === group.jid)
        ),
      });
      return;
    }
    addRule("group", group.jid, group.subject);
  }

  function addVisibleGroups() {
    if (!filters || filteredGroups.length === 0) return;
    const next = [...filters.rules];
    for (const group of filteredGroups) {
      if (next.some((rule) => rule.kind === "group" && rule.value === group.jid)) {
        continue;
      }
      next.push({ kind: "group", value: group.jid, label: group.subject });
    }
    setFilters({ ...filters, rules: next });
  }

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs">Mode</Label>
        <p className="mt-1 mb-2 text-[11px] text-muted-foreground">
          Direct-message handling is currently unavailable on WhatsApp
          (linked-device sessions can&apos;t reliably read self-DMs). Use
          group-based modes for now.
        </p>
        <div className="mt-1 grid sm:grid-cols-2 gap-2">
          <ModeOption
            current={filters.mode}
            value="dms_only"
            label="DMs to me only"
            description="Bot would answer only your direct messages."
            onSelect={setMode}
            disabled
            disabledNote="DMs aren't supported yet on WhatsApp."
          />
          <ModeOption
            current={filters.mode}
            value="allowlist"
            label="Specific contacts & groups"
            description="Bot answers only in conversations you list."
            onSelect={setMode}
          />
          <ModeOption
            current={filters.mode}
            value="denylist"
            label="Everything except listed"
            description="Bot answers everywhere except in conversations you list."
            onSelect={setMode}
          />
          <ModeOption
            current={filters.mode}
            value="all"
            label="Everything"
            description="Bot answers in every chat (DMs and groups)."
            onSelect={setMode}
            disabled
            disabledNote="Includes DMs, which aren't supported yet."
          />
        </div>
      </div>

      {showRulesEditor && (
        <>
          <Separator />

          <div className="space-y-2">
            <Label className="text-xs">Phone numbers</Label>
            <div className="flex gap-2">
              <Input
                value={phoneInput}
                onChange={(e) => setPhoneInput(e.target.value)}
                placeholder="+1 555 1234567"
              />
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  const digits = phoneInput.replace(/\D+/g, "");
                  if (digits) {
                    addRule("phone", digits);
                    setPhoneInput("");
                  }
                }}
              >
                Add
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-end justify-between gap-2">
              <div className="space-y-0.5">
                <Label className="text-xs">Groups</Label>
                <p className="text-[11px] text-muted-foreground">
                  Search and select every group this mode should include.
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={loadGroups}
                disabled={busy}
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
                Load my groups
              </Button>
            </div>

            {groups && groups.length > 0 && (
              <div className="rounded-md border bg-background">
                <div className="flex flex-col gap-2 border-b p-2 sm:flex-row sm:items-center">
                  <div className="relative min-w-0 flex-1">
                    <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={groupSearch}
                      onChange={(e) => setGroupSearch(e.target.value)}
                      placeholder="Search groups by name or jid"
                      className="pl-8"
                    />
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={addVisibleGroups}
                    disabled={filteredGroups.length === 0}
                  >
                    <Check className="h-4 w-4" />
                    Select shown
                  </Button>
                </div>
                <div className="flex items-center justify-between border-b px-3 py-2 text-xs text-muted-foreground">
                  <span>
                    {filteredGroups.length} shown · {selectedGroupIds.size} selected
                  </span>
                  {selectedVisibleCount > 0 ? (
                    <span>{selectedVisibleCount} selected here</span>
                  ) : null}
                </div>
                <div className="max-h-64 overflow-y-auto p-1">
                  {filteredGroups.length === 0 ? (
                    <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                      No groups match this search.
                    </div>
                  ) : (
                    filteredGroups.map((g) => {
                      const checked = selectedGroupIds.has(g.jid);
                      return (
                        <label
                          key={g.jid}
                          className={cn(
                            "flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-left text-xs transition-colors",
                            checked
                              ? "bg-primary/5 text-foreground"
                              : "hover:bg-accent"
                          )}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleGroup(g)}
                            className="h-4 w-4 rounded border-input accent-primary"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">
                              {g.subject}
                            </span>
                            <span className="block truncate font-mono text-[11px] text-muted-foreground">
                              {g.jid}
                            </span>
                          </span>
                          <span className="shrink-0 text-muted-foreground">
                            {g.participants_count} members
                          </span>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>
            )}
            {groups && groups.length === 0 && (
              <div className="text-xs text-muted-foreground">
                No groups found on this account.
              </div>
            )}

            <div className="flex gap-2">
              <Input
                value={inviteInput}
                onChange={(e) => setInviteInput(e.target.value)}
                placeholder="https://chat.whatsapp.com/INVITECODE"
              />
              <Button
                type="button"
                variant="outline"
                onClick={resolveInvite}
                disabled={busy || !inviteInput.trim()}
              >
                Add by invite
              </Button>
            </div>
          </div>

          <Separator />

          <div className="space-y-1">
            <Label className="text-xs">Active rules</Label>
            {filters.rules.length === 0 ? (
              <div className="text-xs text-muted-foreground">No rules yet.</div>
            ) : (
              <ul className="space-y-1">
                {filters.rules.map((r, i) => (
                  <li
                    key={`${r.kind}:${r.value}:${i}`}
                    className="flex items-center justify-between rounded border bg-background px-2 py-1 text-xs"
                  >
                    <span className="font-mono">
                      <Badge variant="muted" className="mr-2 capitalize">
                        {r.kind}
                      </Badge>
                      {r.label ? `${r.label} — ` : ""}
                      {r.value}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => removeRule(i)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      <div className="flex justify-end">
        <Button onClick={save} disabled={savingMode}>
          {savingMode ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
          Save
        </Button>
      </div>
    </div>
  );
}

function ModeOption({
  current,
  value,
  label,
  description,
  onSelect,
  disabled = false,
  disabledNote,
}: {
  current: MessagingFilters["mode"];
  value: MessagingFilters["mode"];
  label: string;
  description: string;
  onSelect: (m: MessagingFilters["mode"]) => void;
  disabled?: boolean;
  disabledNote?: string;
}) {
  const isActive = current === value;
  return (
    <button
      type="button"
      onClick={() => {
        if (disabled) return;
        onSelect(value);
      }}
      disabled={disabled}
      aria-disabled={disabled}
      title={disabled ? disabledNote : undefined}
      className={cn(
        "flex flex-col items-start rounded border p-2 text-left transition-colors text-xs",
        disabled
          ? "cursor-not-allowed opacity-50 bg-muted/40 border-dashed"
          : isActive
            ? "border-primary ring-2 ring-primary/30 bg-primary/5"
            : "hover:border-foreground/30"
      )}
    >
      <span className="text-sm font-medium">
        {label}
        {disabled && (
          <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-normal uppercase tracking-wide text-muted-foreground">
            Unavailable
          </span>
        )}
      </span>
      <span className="text-muted-foreground">{description}</span>
      {disabled && disabledNote && (
        <span className="mt-1 text-[11px] italic text-muted-foreground">
          {disabledNote}
        </span>
      )}
    </button>
  );
}

function AvailablePlugins({
  plugins,
  onLinked,
}: {
  plugins: MessagingPluginInfo[] | null;
  onLinked: () => void;
}) {
  if (plugins === null) return null;
  if (plugins.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">
        No messaging plugins are configured on this server. Check the
        WhatsApp plugin's environment variables to enable it.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div className="text-sm font-medium">Connect a new account</div>
      {plugins.map((p) => (
        <PluginPairCard key={p.id} plugin={p} onLinked={onLinked} />
      ))}
    </div>
  );
}

function PluginPairCard({
  plugin,
  onLinked,
}: {
  plugin: MessagingPluginInfo;
  onLinked: () => void;
}) {
  const [session, setSession] = useState<MessagingPairSession | null>(null);
  const [loading, setLoading] = useState(false);

  async function start() {
    setLoading(true);
    try {
      const s = await api.startPairSession(plugin.id);
      setSession(s);
    } catch (e) {
      toast.error("Failed to start pairing", {
        description: (e as Error).message,
      });
    } finally {
      setLoading(false);
    }
  }

  // Poll bridge state while pairing in flight.
  useEffect(() => {
    if (!session) return;
    if (session.state === "paired" || session.state === "failed") return;
    const id = setInterval(async () => {
      try {
        const next = await api.getPairSession(session.pair_id);
        setSession(next);
        if (next.state === "paired") {
          toast.success(`Connected ${plugin.name}`, {
            description: next.phone_number ? `+${next.phone_number}` : undefined,
          });
          onLinked();
          clearInterval(id);
        } else if (next.state === "failed") {
          toast.error("Pairing failed", { description: next.failure_reason ?? undefined });
          clearInterval(id);
        }
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => clearInterval(id);
  }, [session, onLinked, plugin.name]);

  const state = session?.state;

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">{plugin.name}</div>
          {plugin.description && (
            <div className="text-xs text-muted-foreground mt-0.5">
              {plugin.description}
            </div>
          )}
        </div>
        <Button
          onClick={start}
          disabled={loading || state === "qr" || state === "waiting"}
          size="sm"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : session ? (
            <RefreshCw className="h-4 w-4 mr-1" />
          ) : (
            <Plus className="h-4 w-4 mr-1" />
          )}
          {state === "paired" ? "Pair another" : session ? "Restart" : "Connect"}
        </Button>
      </div>

      {session && state !== "paired" && state !== "failed" && (
        <div className="rounded-md bg-muted/40 p-4 flex flex-col sm:flex-row items-start gap-4">
          {session.qr_image_b64 ? (
            <img
              src={session.qr_image_b64}
              alt="WhatsApp pairing QR"
              className="bg-white rounded p-2 shrink-0 w-[192px] h-[192px]"
            />
          ) : (
            <div className="w-[192px] h-[192px] flex items-center justify-center text-xs text-muted-foreground bg-white/40 rounded">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          )}
          <div className="space-y-2 text-sm min-w-0">
            <div className="font-medium">Scan with WhatsApp</div>
            <ol className="list-decimal pl-4 text-muted-foreground space-y-1 text-xs">
              <li>Open WhatsApp on your phone.</li>
              <li>
                Go to <b>Settings → Linked Devices → Link a Device</b>.
              </li>
              <li>Point your phone at this QR code.</li>
            </ol>
            <div className="text-xs text-muted-foreground">
              Status: <span className="font-mono">{state ?? "waiting"}</span>
            </div>
          </div>
        </div>
      )}

      {state === "paired" && session?.phone_number && (
        <div className="rounded-md bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm">
          Connected as <b>+{session.phone_number}</b>. You can now message
          your bot from WhatsApp.
        </div>
      )}

      {state === "failed" && (
        <div className="rounded-md bg-destructive/10 border border-destructive/30 px-3 py-2 text-sm text-destructive">
          Pairing failed{session?.failure_reason ? `: ${session.failure_reason}` : "."}{" "}
          Click <b>Restart</b> to try again.
        </div>
      )}
    </div>
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
  const [exporting, setExporting] = useState(false);
  const [wiping, setWiping] = useState(false);
  const { logout } = useAuth();

  async function exportData() {
    setExporting(true);
    try {
      const { blob, filename } = await api.exportMyData();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error("Export failed", { description: (e as Error).message });
    } finally {
      setExporting(false);
    }
  }

  async function wipeData() {
    const first = confirm(
      "This permanently deletes your projects, resumes, sessions, memory, messaging links, and provider keys. Your login account remains."
    );
    if (!first) return;
    const confirmation = prompt('Type "WIPE" to confirm.');
    if (confirmation !== "WIPE") return;
    setWiping(true);
    try {
      await api.wipeMyData();
      toast.success("Data wiped", {
        description: "Your account remains, but workspace data was removed.",
      });
      logout();
    } catch (e) {
      toast.error("Wipe failed", { description: (e as Error).message });
    } finally {
      setWiping(false);
    }
  }

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
          <Button variant="outline" onClick={exportData} disabled={exporting}>
            {exporting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            Export everything
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
          <Button variant="destructive" onClick={wipeData} disabled={wiping}>
            {wiping ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            Wipe my data
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
