export interface TokenPair {
  access_token: string;
  refresh_token: string;
  access_expires_at: string;
  refresh_expires_at: string;
}

export interface UserOut {
  id: string;
  email: string;
  display_name: string;
  tier: string;
  is_admin: boolean;
  created_at: string;
}

export interface AdminUserUpdateRequest {
  tier?: string | null;
  is_admin?: boolean | null;
}

export interface ApiKey {
  id: string;
  provider: string;
  label: string;
  created_at: string;
}

export type ModelRole =
  | "chat"
  | "embedding"
  | "transcription"
  | "voice-analysis";

export interface ModelPreferenceOut {
  role: ModelRole;
  provider: string;
  endpoint: string;
  model_id: string;
  updated_at: string | null;
}

export interface ModelPreferenceBody {
  provider: string;
  endpoint: string;
  model_id: string;
}

export interface ProviderModel {
  id: string;
  owned_by: string | null;
  created: number | null;
}

export interface ProviderModelList {
  provider: string;
  endpoint: string;
  models: ProviderModel[];
}

export interface ProviderTestResponse {
  ok: boolean;
  latency_ms: number;
  error: string | null;
}

export interface ProjectOut {
  id: string;
  name: string;
  source_type: string;
  status: string;
  summary: string | null;
  created_at: string;
}

export interface ProjectDetail extends ProjectOut {
  architecture: any | null;
  interesting_decisions: any | null;
}

export interface ProjectFileOut {
  id: string;
  rel_path: string;
  language: string | null;
  bytes: number;
  summary: string | null;
}

export interface ProjectDiagramOut {
  id: string;
  name: string;
  kind: string;
  mermaid: string;
}

export interface IngestRunOut {
  id: string;
  kind: string;
  status: string;
  step: string | null;
  progress: number;
  error: string | null;
  project_id: string | null;
  resume_id: string | null;
  created_at: string;
}

export interface ResumeOut {
  id: string;
  original_filename: string;
  content_type: string;
  created_at: string;
}

export interface ResumeDetail extends ResumeOut {
  text: string | null;
  parsed: any | null;
}

export interface ClaimMappingOut {
  id: string;
  claim: string;
  project_id: string | null;
  grounding: any | null;
  confidence: number;
}

// ----- Common KB -----

export interface CommonKBSpaceOut {
  id: string;
  key: string;
  name: string;
  description: string | null;
  enabled: boolean;
  created_at: string;
}

export interface CommonKBSourceOut {
  id: string;
  space_id: string;
  key: string;
  name: string;
  source_type: string;
  base_url: string | null;
  license: string | null;
  allowed_use: any | null;
  refresh_status: string;
  last_error: string | null;
  created_at: string;
}

export interface CommonKBDocumentOut {
  id: string;
  space_id: string;
  source_id: string | null;
  title: string;
  filename: string | null;
  content_type: string | null;
  blob_path: string | null;
  canonical_url: string | null;
  content_hash: string | null;
  status: string;
  error: string | null;
  meta: any | null;
  tags: string[];
  create_embeddings: boolean;
  created_at: string;
}

export interface CommonKBItemOut {
  id: string;
  space_id: string;
  source_id: string | null;
  document_id: string | null;
  item_type: string;
  category: string;
  title: string;
  question: string | null;
  answer_outline: string | null;
  content: string | null;
  difficulty: number;
  role_family: string | null;
  level: string | null;
  company: string | null;
  language: string | null;
  provenance: any | null;
  status: string;
  version: number;
  tags: string[];
  created_at: string;
}

export interface CompanyInterviewProfileOut {
  id: string;
  company_key: string;
  company: string;
  role_family: string | null;
  category_weights: Record<string, number> | null;
  language_preferences: string[] | null;
  round_patterns: any[] | null;
  confidence: number;
  source_refs: any[] | null;
  item_count: number;
  created_at: string;
}

export interface InterviewPreference {
  id?: string | null;
  user_id?: string | null;
  target_company?: string | null;
  category_weights?: Record<string, number> | null;
  languages: string[];
  interview_style?: string | null;
  include_company_style: boolean;
  created_at?: string | null;
}

// ----- QA -----

export interface QAEvidence {
  rel_path: string;
  start_line: number;
  end_line: number;
  snippet: string;
}

export interface QAItemOut {
  id: string;
  category: string;
  level: string;
  question: string;
  ideal_answer: string;
  evidence: QAEvidence[];
  difficulty: number;
  tags: string[];
}

export interface QASetOut {
  id: string;
  project_id: string;
  position: string;
  level: string;
  status: string;
  total: number;
  error: string | null;
  created_at: string;
}

export interface QASetDetail extends QASetOut {
  items: QAItemOut[];
}

// ----- Chat -----

export interface ChatSessionOut {
  id: string;
  mode: string;
  title: string | null;
  project_id: string | null;
  target: any | null;
  status: string;
  turn_count: number;
  created_at: string;
}

export interface ChatMessageOut {
  id: string;
  session_id: string;
  role: string;
  content: string;
  meta: any | null;
  created_at: string;
}

export interface RealtimeTicket {
  ws_url: string;
  ticket: string;
  expires_at: number;
}

export interface InterviewEvaluationOut {
  id: string;
  session_id: string;
  overall_score: number;
  scores: Record<string, number> | null;
  summary: string | null;
  strengths: string[];
  weaknesses: string[];
  suggested_practice: { area: string; why: string; next_step: string }[];
  delivery_score: number | null;
  delivery_summary: {
    metrics?: {
      turn_count?: number;
      total_duration_s?: number;
      avg_wpm?: number | null;
      filler_counts?: { word: string; count: number }[];
      total_pause_count?: number;
      total_long_pauses?: number;
      avg_tone?: {
        confidence?: number | null;
        energy?: number | null;
        monotone?: number | null;
      };
      avg_language_accuracy?: number | null;
      language_issues?: string[];
      pronunciation_issues?: { word: string; note?: string }[];
    };
    feedback?: ({ area?: string; note?: string } | string)[];
  } | null;
  created_at: string;
}

const BASE = "/api/v1";
const ACCESS_KEY = "access_token";
const REFRESH_KEY = "refresh_token";

export function getToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}
export function setTokens(access: string | null, refresh?: string | null): void {
  if (access) localStorage.setItem(ACCESS_KEY, access);
  else localStorage.removeItem(ACCESS_KEY);
  if (refresh !== undefined) {
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
    else localStorage.removeItem(REFRESH_KEY);
  }
}
// Back-compat
export function setToken(t: string | null): void {
  setTokens(t);
}

class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let refreshInFlight: Promise<string | null> | null = null;

async function tryRefresh(): Promise<string | null> {
  const rt = getRefreshToken();
  if (!rt) return null;
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) {
        setTokens(null, null);
        return null;
      }
      const tp = (await res.json()) as TokenPair;
      setTokens(tp.access_token, tp.refresh_token);
      return tp.access_token;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function rawFetch(
  path: string,
  init: RequestInit & { auth?: boolean; isJson?: boolean } = {}
): Promise<Response> {
  const { auth = true, isJson = true, headers, ...rest } = init;
  const finalHeaders: Record<string, string> = { ...(headers as any) };
  if (isJson && !(rest.body instanceof FormData)) {
    finalHeaders["Content-Type"] = "application/json";
  }
  if (auth) {
    const t = getToken();
    if (t) finalHeaders["Authorization"] = `Bearer ${t}`;
  }
  return fetch(`${BASE}${path}`, { ...rest, headers: finalHeaders });
}

async function request<T>(
  path: string,
  init: RequestInit & { auth?: boolean; isJson?: boolean } = {}
): Promise<T> {
  let res = await rawFetch(path, init);
  if (res.status === 401 && (init.auth ?? true)) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      res = await rawFetch(path, init);
    }
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: any = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    const detail =
      (body && typeof body === "object" && "detail" in body && body.detail) ||
      (typeof body === "string" ? body : `HTTP ${res.status}`);
    throw new HttpError(res.status, String(detail));
  }
  return body as T;
}

export const api = {
  // auth
  register: (email: string, password: string, display_name: string) =>
    request<UserOut>("/auth/register", {
      method: "POST",
      auth: false,
      body: JSON.stringify({ email, password, display_name }),
    }),
  login: (email: string, password: string) =>
    request<TokenPair>("/auth/login", {
      method: "POST",
      auth: false,
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<UserOut>("/me"),

  // admin users
  adminListUsers: () => request<UserOut[]>("/admin/users"),
  adminUpdateUser: (id: string, body: AdminUserUpdateRequest) =>
    request<UserOut>(`/admin/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  // api keys
  listApiKeys: () => request<ApiKey[]>("/me/api-keys"),
  addApiKey: (provider: string, label: string, plaintext: string) =>
    request<ApiKey>("/me/api-keys", {
      method: "POST",
      body: JSON.stringify({ provider, label, plaintext }),
    }),
  deleteApiKey: (id: string) =>
    request<void>(`/me/api-keys/${id}`, { method: "DELETE" }),

  // model preferences
  listModelPreferences: () =>
    request<ModelPreferenceOut[]>("/me/model-preferences"),
  upsertModelPreference: (role: ModelRole, body: ModelPreferenceBody) =>
    request<ModelPreferenceOut>(`/me/model-preferences/${role}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteModelPreference: (role: ModelRole) =>
    request<void>(`/me/model-preferences/${role}`, { method: "DELETE" }),
  testModelPreference: (role: ModelRole, body: ModelPreferenceBody) =>
    request<ProviderTestResponse>(
      `/me/model-preferences/${role}/test`,
      { method: "POST", body: JSON.stringify(body) }
    ),
  listProviderModels: (provider: string, endpoint: string) =>
    request<ProviderModelList>(
      `/providers/${provider}/models?endpoint=${encodeURIComponent(endpoint)}`
    ),

  // projects
  listProjects: () => request<ProjectOut[]>("/projects"),
  uploadProject: (name: string, file: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("file", file);
    return request<ProjectOut>("/projects", {
      method: "POST",
      body: fd,
      isJson: false,
    });
  },
  getProject: (id: string) => request<ProjectDetail>(`/projects/${id}`),
  listProjectFiles: (id: string) =>
    request<ProjectFileOut[]>(`/projects/${id}/files`),
  listProjectDiagrams: (id: string) =>
    request<ProjectDiagramOut[]>(`/projects/${id}/diagrams`),
  getRun: (projectId: string, runId: string) =>
    request<IngestRunOut>(`/projects/${projectId}/runs/${runId}`),
  runProjectNow: (id: string) =>
    request<{ run_id: string; status: string }>(
      `/projects/${id}/_run_now`,
      { method: "POST" }
    ),

  // resumes
  uploadResume: (file: File, projectIds: string[]) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("project_ids", projectIds.join(","));
    return request<ResumeOut>("/resumes", {
      method: "POST",
      body: fd,
      isJson: false,
    });
  },
  listResumes: () => request<ResumeOut[]>("/resumes"),
  getResume: (id: string) => request<ResumeDetail>(`/resumes/${id}`),
  deleteResume: (id: string) =>
    request<void>(`/resumes/${id}`, { method: "DELETE" }),
  transcribeAudio: async (
    audio: Blob,
    language?: string
  ): Promise<{ text: string }> => {
    const fd = new FormData();
    const ext = (audio.type.split("/")[1] || "webm").split(";")[0];
    fd.append("file", audio, `audio.${ext}`);
    if (language) fd.append("language", language);
    return request<{ text: string }>("/audio/transcribe", {
      method: "POST",
      body: fd,
      isJson: false,
    });
  },
  fetchResumeFile: async (
    id: string,
    inline = true
  ): Promise<{ blob: Blob; filename: string; contentType: string }> => {
    const path = `/resumes/${id}/file?inline=${inline ? "true" : "false"}`;
    let res = await rawFetch(path);
    if (res.status === 401) {
      const refreshed = await tryRefresh();
      if (refreshed) res = await rawFetch(path);
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new HttpError(res.status, text || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    return {
      blob,
      filename: m ? decodeURIComponent(m[1]) : `resume-${id}`,
      contentType: res.headers.get("Content-Type") || "application/octet-stream",
    };
  },
  listClaimMappings: (id: string) =>
    request<ClaimMappingOut[]>(`/resumes/${id}/claim-mappings`),
  runResumeNow: (id: string, projectIds: string[]) =>
    request<{ run_id: string; status: string }>(
      `/resumes/${id}/_run_now?project_ids=${encodeURIComponent(
        projectIds.join(",")
      )}`,
      { method: "POST" }
    ),

  // common KB
  listKBSpaces: () => request<CommonKBSpaceOut[]>("/kb/spaces"),
  listCompanyProfiles: (query = "") =>
    request<CompanyInterviewProfileOut[]>(
      `/kb/company-profiles${query ? `?query=${encodeURIComponent(query)}` : ""}`
    ),
  listKBItems: (params: { space?: string; tag?: string; company?: string; category?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.space) q.set("space", params.space);
    if (params.tag) q.set("tag", params.tag);
    if (params.company) q.set("company", params.company);
    if (params.category) q.set("category", params.category);
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return request<CommonKBItemOut[]>(`/kb/items${suffix}`);
  },
  getInterviewPreferences: () =>
    request<InterviewPreference>("/me/interview-preferences"),
  putInterviewPreferences: (body: InterviewPreference) =>
    request<InterviewPreference>("/me/interview-preferences", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // admin KB
  adminListSpaces: () => request<CommonKBSpaceOut[]>("/admin/kb/spaces"),
  adminCreateSpace: (body: { key: string; name: string; description?: string | null; enabled?: boolean }) =>
    request<CommonKBSpaceOut>("/admin/kb/spaces", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminListSources: (space?: string) =>
    request<CommonKBSourceOut[]>(
      `/admin/kb/sources${space ? `?space=${encodeURIComponent(space)}` : ""}`
    ),
  adminCreateSource: (body: {
    space_key: string;
    key: string;
    name: string;
    source_type: string;
    base_url?: string | null;
    license?: string | null;
    allowed_use?: any;
  }) =>
    request<CommonKBSourceOut>("/admin/kb/sources", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminRefreshSource: (id: string) =>
    request<{ status: string }>(`/admin/kb/sources/${id}:refresh`, {
      method: "POST",
    }),
  adminUploadDocument: (
    spaceKey: string,
    file: File,
    sourceId?: string,
    title?: string,
    tags: string[] = [],
    createEmbeddings = true
  ) => {
    const fd = new FormData();
    fd.append("space_key", spaceKey);
    if (sourceId) fd.append("source_id", sourceId);
    if (title) fd.append("title", title);
    if (tags.length > 0) fd.append("tags", JSON.stringify(tags));
    fd.append("create_embeddings", createEmbeddings ? "true" : "false");
    fd.append("file", file);
    return request<CommonKBDocumentOut>("/admin/kb/documents", {
      method: "POST",
      body: fd,
      isJson: false,
    });
  },
  adminListDocuments: (
    params: string | { space?: string; status?: string; limit?: number } = {}
  ) => {
    const q = new URLSearchParams();
    if (typeof params === "string") {
      if (params) q.set("space", params);
    } else {
      if (params.space) q.set("space", params.space);
      if (params.status) q.set("status", params.status);
      if (params.limit) q.set("limit", String(params.limit));
    }
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return request<CommonKBDocumentOut[]>(`/admin/kb/documents${suffix}`);
  },
  adminDeleteDocument: (id: string) =>
    request<void>(`/admin/kb/documents/${id}`, {
      method: "DELETE",
    }),
  adminProcessDocument: (id: string) =>
    request<{ status: string }>(`/admin/kb/documents/${id}:process`, {
      method: "POST",
    }),
  adminListItems: (
    params: {
      space?: string;
      tag?: string;
      company?: string;
      category?: string;
      language?: string;
      limit?: number;
    } = {}
  ) => {
    const q = new URLSearchParams();
    if (params.space) q.set("space", params.space);
    if (params.tag) q.set("tag", params.tag);
    if (params.company) q.set("company", params.company);
    if (params.category) q.set("category", params.category);
    if (params.language) q.set("language", params.language);
    if (params.limit) q.set("limit", String(params.limit));
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return request<CommonKBItemOut[]>(`/admin/kb/items${suffix}`);
  },
  adminCreateItem: (body: any) =>
    request<CommonKBItemOut>("/admin/kb/items", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminRebuildCompanyProfiles: () =>
    request<{ status: string }>("/admin/kb/company-profiles:rebuild", {
      method: "POST",
    }),

  // qa
  generateQA: (projectId: string, position: string, levels: string[]) =>
    request<{ qa_set_ids: string[] }>(
      `/projects/${projectId}/qa:generate`,
      { method: "POST", body: JSON.stringify({ position, levels }) }
    ),
  listQASets: (projectId: string) =>
    request<QASetOut[]>(`/projects/${projectId}/qa`),
  getQASet: (id: string) => request<QASetDetail>(`/qa-sets/${id}`),
  regenerateQASet: (id: string) =>
    request<QASetOut>(`/qa-sets/${id}:regenerate`, { method: "POST" }),

  // mentor
  createMentorSession: (project_id: string | null, title: string | null) =>
    request<ChatSessionOut>("/mentor/sessions", {
      method: "POST",
      body: JSON.stringify({ project_id, title }),
    }),
  listMentorSessions: () =>
    request<ChatSessionOut[]>("/mentor/sessions"),
  listMentorMessages: (id: string) =>
    request<ChatMessageOut[]>(`/mentor/sessions/${id}/messages`),
  endMentorSession: (id: string) =>
    request<ChatSessionOut>(`/mentor/sessions/${id}:end`, { method: "POST" }),
  renameMentorSession: (id: string, title: string | null) =>
    request<ChatSessionOut>(`/mentor/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  // general /chat (workspace-aware, no project pin, no tools)
  createGeneralSession: (title: string | null) =>
    request<ChatSessionOut>("/general/sessions", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  listGeneralSessions: () =>
    request<ChatSessionOut[]>("/general/sessions"),
  listGeneralMessages: (id: string) =>
    request<ChatMessageOut[]>(`/general/sessions/${id}/messages`),
  endGeneralSession: (id: string) =>
    request<ChatSessionOut>(`/general/sessions/${id}:end`, { method: "POST" }),
  renameGeneralSession: (id: string, title: string | null) =>
    request<ChatSessionOut>(`/general/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  // interviewer
  createInterviewerSession: (
    body: {
      resume_id?: string;
      project_id?: string;
      position: string;
      level: string;
      n_questions: number;
      target_company?: string;
      preferences?: {
        category_weights?: Record<string, number>;
        languages?: string[];
        include_company_style?: boolean;
      };
    }
  ) =>
    request<ChatSessionOut>("/interviewer/sessions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listInterviewerSessions: () =>
    request<ChatSessionOut[]>("/interviewer/sessions"),
  listInterviewerMessages: (id: string) =>
    request<ChatMessageOut[]>(`/interviewer/sessions/${id}/messages`),
  endInterviewerSession: (id: string) =>
    request<InterviewEvaluationOut>(
      `/interviewer/sessions/${id}:end`,
      { method: "POST" }
    ),
  getInterviewerEvaluation: (id: string) =>
    request<InterviewEvaluationOut>(
      `/interviewer/sessions/${id}/evaluation`
    ),
  renameInterviewerSession: (id: string, title: string | null) =>
    request<ChatSessionOut>(`/interviewer/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  getRealtimeTicket: (id: string) =>
    request<RealtimeTicket>(
      `/interviewer/sessions/${id}/realtime/ticket`,
      { method: "POST" }
    ),

  // messaging (whatsapp / future channels)
  listMessagingPlugins: () =>
    request<MessagingPluginInfo[]>("/messaging/plugins"),
  startPairSession: (channel: string) =>
    request<MessagingPairSession>("/messaging/pair-sessions", {
      method: "POST",
      body: JSON.stringify({ channel }),
    }),
  getPairSession: (pair_id: string) =>
    request<MessagingPairSession>(`/messaging/pair-sessions/${pair_id}`),
  listMessagingLinks: () =>
    request<MessagingLinkOut[]>("/messaging/links"),
  deleteMessagingLink: (id: string) =>
    request<void>(`/messaging/links/${id}`, { method: "DELETE" }),
  listLinkGroups: (id: string) =>
    request<MessagingGroup[]>(`/messaging/links/${id}/groups`),
  resolveLinkInvite: (id: string, code: string) =>
    request<MessagingGroup>(`/messaging/links/${id}/resolve-invite`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
  getLinkFilters: (id: string) =>
    request<MessagingFilters>(`/messaging/links/${id}/filters`),
  putLinkFilters: (id: string, body: MessagingFilters) =>
    request<MessagingFilters>(`/messaging/links/${id}/filters`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};

export interface MessagingGroup {
  jid: string;
  subject: string;
  participants_count: number;
}

export interface MessagingFilterRule {
  kind: "phone" | "group";
  value: string;
  label?: string | null;
}

export interface MessagingFilters {
  mode: "dms_only" | "allowlist" | "denylist" | "all";
  rules: MessagingFilterRule[];
}

export interface MessagingPluginInfo {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
}

export interface MessagingPairSession {
  pair_id: string;
  channel: string;
  state: "waiting" | "qr" | "paired" | "failed";
  qr_image_b64: string | null;
  qr_text: string | null;
  phone_number: string | null;
  failure_reason: string | null;
}

export interface MessagingLinkOut {
  id: string;
  channel: string;
  external_id: string;
  display_name: string | null;
  last_seen_at: string | null;
  created_at: string;
  filter_mode: "dms_only" | "allowlist" | "denylist" | "all";
}

// ---------- SSE streaming helper ----------
//
// We POST and read the response body as a stream, parsing SSE frames manually.
// The fetch+ReadableStream approach lets us keep auth headers and JSON body.

export interface SSEEvent {
  event: string;
  data: any;
}

async function consumeSSE(
  res: Response,
  onEvent: (e: SSEEvent) => void
): Promise<void> {
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new HttpError(res.status, text || `HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const ev = parseFrame(block);
      if (ev) onEvent(ev);
    }
  }
  if (buf.trim()) {
    const ev = parseFrame(buf);
    if (ev) onEvent(ev);
  }
}

export async function postSSE(
  path: string,
  body: any,
  onEvent: (e: SSEEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  async function open(): Promise<Response> {
    const t = getToken();
    return fetch(`${BASE}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(t ? { Authorization: `Bearer ${t}` } : {}),
      },
      body: JSON.stringify(body),
      signal,
    });
  }
  let res = await open();
  if (res.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) res = await open();
  }
  return consumeSSE(res, onEvent);
}

export async function postMultipartSSE(
  path: string,
  formData: FormData,
  onEvent: (e: SSEEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  async function open(): Promise<Response> {
    const t = getToken();
    return fetch(`${BASE}${path}`, {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        ...(t ? { Authorization: `Bearer ${t}` } : {}),
      },
      body: formData,
      signal,
    });
  }
  let res = await open();
  if (res.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) res = await open();
  }
  return consumeSSE(res, onEvent);
}

function parseFrame(block: string): SSEEvent | null {
  let event = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) };
  } catch {
    return { event, data };
  }
}

export { HttpError };
