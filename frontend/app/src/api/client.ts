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

export interface ApiKey {
  id: string;
  provider: string;
  label: string;
  created_at: string;
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

export interface InterviewEvaluationOut {
  id: string;
  session_id: string;
  overall_score: number;
  scores: Record<string, number> | null;
  summary: string | null;
  strengths: string[];
  weaknesses: string[];
  suggested_practice: { area: string; why: string; next_step: string }[];
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

  // api keys
  listApiKeys: () => request<ApiKey[]>("/me/api-keys"),
  addApiKey: (provider: string, label: string, plaintext: string) =>
    request<ApiKey>("/me/api-keys", {
      method: "POST",
      body: JSON.stringify({ provider, label, plaintext }),
    }),
  deleteApiKey: (id: string) =>
    request<void>(`/me/api-keys/${id}`, { method: "DELETE" }),

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
