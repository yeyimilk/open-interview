# Open Interview — Requirements & System Design

Status: Draft v0.1 (pre-implementation)
Owner: TBD
Last updated: 2026-04-30

---

## 0. Purpose

A self-hosted, multi-user interview-preparation platform for software engineers (with first-class support for Applied AI roles, across levels Junior → Principal / Tech Lead). Users upload their own projects and resume; the system deeply understands them, generates grounded interview Q&A, and offers two AI-powered interactive modes — **Mentor** (open-ended coach) and **Interviewer** (mock interview with evaluation). The platform maintains long-lived per-user memory so coaching improves over time.

No code will be written until this document is approved.

---

## 1. Product Requirements

### 1.1 Personas

- **Candidate** — primary user. Software engineer preparing for interviews. Uploads projects, resume, picks target positions/levels, uses Mentor and Interviewer modes.
- **Admin** — operates the self-hosted instance. Manages users, paid tiers, rate limits, model gateway config, and common KB refresh.

### 1.2 Target positions & levels (v1 calibration matrix)

Position families (multi-select per user):
- Generic Software Engineer
- Applied AI Engineer (LLM, RAG, agents, eval)

Levels:

| Level | Focus signals |
|---|---|
| Junior | Implementation correctness, basic data structures, ability to learn |
| Mid | Tradeoffs, testing, code quality, ownership of features |
| Senior | Design choices, scalability, mentoring signal, ambiguity handling |
| Staff | Cross-team impact, technical strategy, deep ambiguity, multi-system reasoning |
| Principal | Org-wide architecture, long-term bets, technical leadership |
| Tech Lead | Delivery, prioritization, people + technical balance |

### 1.3 Functional requirements

**FR-1 Authentication & multi-tenancy**
- Email/password registration & login; JWT-based sessions.
- All data is isolated per `user_id`. No cross-user reads.
- Admin role can manage users, tiers, gateway config, common KB.

**FR-2 Onboarding & uploads**
- User can upload one or more projects (zip, git URL, or folder upload). Source code + docs both supported.
- User can upload a resume (PDF, DOCX, MD).
- User can select one or more target positions, each with a level.

**FR-3 Project ingestion & understanding**
For each project, the system produces and stores:
- (a) High-level architecture summary
- (b) Per-module / per-file summaries (tree-sitter chunked)
- (c) Auto-generated flow / sequence diagrams (Mermaid)
- (d) "Interesting decisions" list (tech choices, tradeoffs, risks)
- (e) Resume-claim ↔ project-fact mapping

**FR-4 QA pre-generation (sharded)**
- Generate grounded Q&A per `(project × position × level)`.
- Generation runs in **batches of 5–10 questions per round**, each batch persisted to a **temp shard file** on disk; final merge produces the canonical per-position QA set.
- Resumable on crash/restart.
- Each Q&A entry stored with rich metadata (see §4.4).
- Default target: ≥ 50 grounded Q&A per `(project × position × level)` selection.
- Expansion on demand from the UI.

**FR-5 Mentor mode**
- Open-ended chat with the user.
- Has access to: private KB (projects, resume, generated QA), common KB, full chat history, episodic memory, semantic profile memory.
- Coaches on technical content **and** communication (phrasing, tone, structure, storytelling).
- Suggests next focus areas based on profile memory.

**FR-6 Interviewer mode**
- Drives a mock interview: picks a question set scoped by selected position/level, asks one question at a time, accepts answers, asks follow-ups.
- At session end, produces a structured evaluation against the rubric (§3.5).
- Writes evaluation events into episodic memory; distillation job updates semantic profile memory so Mentor can react.

**FR-7 Memory subsystem**
- 3 layers per user:
  - Raw chat logs (full fidelity, every message in both modes).
  - Episodic memory (per-session summaries + Interviewer evaluation events).
  - Semantic profile memory (strengths, weaknesses, communication notes, goals, recommended focus).
- Full chat history is persisted indefinitely (subject to user's "wipe" action).

**FR-8 Common KB (v1)**
- Read-only KB shared across users, refreshable by admin command.
- v1 sources: `applied_ai_questions`, `system_design_primer`.
- Storage policy: **questions + our own generated answers only**; no copyrighted solutions are scraped/stored.
- An inventory file `COMMON_KB_INVENTORY.md` lists what is included and what is intentionally excluded.

**FR-9 GenAI Model Gateway (separate service)**
- All LLM and embedding calls from the core service go through the Gateway.
- Backends: any OpenAI-compatible endpoint (OpenAI, Anthropic via adapter, Ollama, vLLM, LM Studio, Together, OpenRouter).
- BYO-key path: when the user has stored their own API key, that key is used; **no rate or token limits enforced**; full request/response/usage is still logged.
- Shared-key path: admin keys are used; **request rate limits per tier** enforced; full usage logged.
- Logical model routing: core service requests "chat" / "embedding" with logical model id; Gateway resolves provider+endpoint+credentials.

**FR-10 Voice readiness (v1 = text-only)**
- All chat I/O goes through a transport-agnostic message interface so STT/TTS adapters can plug in for v2 without rewrites.

**FR-11 Privacy & data control**
- Per-user "wipe my data" action.
- Per-user export action (zip of memory + chat history + generated QA + uploaded artifacts metadata).
- No telemetry by default.

### 1.4 Non-functional requirements

- **NFR-1 Self-hostable** on a single Docker Compose stack.
- **NFR-2 Multi-tenant isolation** at DB row level + namespaced vector collections + per-user filesystem paths for blobs.
- **NFR-3 Resumability**: ingestion and QA generation must resume after crash without losing committed shards.
- **NFR-4 Observability**: structured logs, request ids, gateway usage events, ingestion job metrics.
- **NFR-5 Performance (MVP)**: ingest a 50k-LOC project + resume in < 10 minutes on a developer laptop using a cloud LLM provider.
- **NFR-6 Security**: secrets (user API keys, JWT secret) encrypted at rest using a server master key; passwords hashed with argon2.
- **NFR-7 Pluggable LLM backends** via Gateway abstraction.
- **NFR-8 No code execution of uploaded projects** in v1 (parsing/static analysis only).

### 1.5 MVP acceptance criteria

- Multi-user server stack runs via `docker compose up`.
- A user can register, log in, store their own API key (optional), upload a project + resume, pick at least one position+level, and complete ingestion.
- ≥ 50 grounded Q&A produced per selected `(project × position × level)`, sharded then merged.
- Mentor chat works with persistent 3-layer memory across sessions.
- Interviewer session ends with a structured evaluation that demonstrably updates semantic profile memory.
- Common KB seeded with `applied_ai_questions` + `system_design_primer`.
- Gateway records full token + model usage for every call (BYO-key and shared-key paths).
- Per-user data isolation verified by automated test (User A cannot read User B's data through any API).

---

## 2. High-level Architecture

### 2.1 Service map

```
+--------------------+         +-------------------------+
|  Web UI (React)    | <-----> |   Core API (FastAPI)    |
|  served at         |  HTTPS  |   - Auth                |
|  http://localhost  |         |   - Projects/Resume     |
+--------------------+         |   - QA / KB             |
                               |   - Mentor / Interviewer|
                               |   - Memory              |
                               +-----------+-------------+
                                           |
                              +------------+------------+
                              |                         |
                  +-----------v-----------+   +---------v----------+
                  |   Worker(s) (RQ /     |   |  GenAI Gateway     |
                  |   Celery / arq)       |   |  (FastAPI)         |
                  |   - Ingestion         |   |  - Provider routing|
                  |   - QA gen (sharded)  |   |  - Rate limits     |
                  |   - Distillation      |   |  - Token accounting|
                  +-----------+-----------+   |  - Key vault       |
                              |               +---------+----------+
                              |                         |
                  +-----------v---------+               |
                  |   Vector DB         |               |
                  |   (Chroma)          |               |
                  +---------------------+               |
                              |                         |
                  +-----------v---------+               |
                  |   PostgreSQL        |               |
                  |   - users, tiers    |               |
                  |   - projects        |               |
                  |   - QA              |               |
                  |   - chat history    |               |
                  |   - memory          |               |
                  |   - gateway logs    |               |
                  +---------------------+               |
                                                        |
                                              +---------v----------+
                                              | LLM providers      |
                                              | (any OpenAI-       |
                                              |  compatible)       |
                                              +--------------------+

   Object/blob store: local filesystem under  /var/openinterview/blobs/<user_id>/...
```

### 2.2 Process boundaries

- **Web UI** — static SPA served by Core API or a sidecar.
- **Core API** — primary application, multi-tenant, user-facing endpoints.
- **Workers** — background jobs (ingestion, QA generation, memory distillation). Multiple processes OK.
- **GenAI Gateway** — independent service. Core/Workers only know it through an internal HTTP API; provider details are invisible to the rest of the system.
- **PostgreSQL** — single source of truth for relational data.
- **Vector DB (Chroma)** — embeddings for code chunks, docs, QA, common KB, memory facts.
- **Blob store** — uploaded zips, extracted source trees, generated diagrams.

---

## 3. Detailed Component Designs

### 3.1 Authentication & user model

- Registration: email + password (argon2-hashed) + display name.
- Login: returns short-lived JWT (access) + refresh token.
- Per-user fields: `tier` (free/paid; admin-configurable), `byo_keys` (encrypted), `created_at`, `is_admin`.
- Admin endpoints gated by `is_admin`.
- Authorization: every resource carries `user_id`; middleware injects the current user; queries filter by it.

### 3.2 Ingestion pipeline (worker job)

Input: `project_id` (or resume_id).
Steps:
1. **Extract**: unzip / clone, build a file tree, ignore binaries and `.git`, `node_modules`, etc.
2. **Classify**: detect languages and frameworks; identify entry points, configs, tests, docs.
3. **AST chunk** (code): tree-sitter parses each source file; chunks at function/class boundaries with sliding window for oversize symbols.
4. **Doc chunk**: markdown/PDF parsed; semantic chunking (headings + length cap).
5. **Embed**: chunks embedded via Gateway → stored in Chroma collection `user_<id>_project_<pid>`.
6. **Summarize (hierarchical)**:
   - Per-file summary (LLM, with code chunk context).
   - Per-module/folder summary (rolls up file summaries).
   - Project-level architecture summary.
7. **Diagrams**: derive component diagram + 1–3 sequence diagrams from architecture summary; render Mermaid; store as text + SVG.
8. **Interesting decisions**: dedicated LLM pass extracts decisions/tradeoffs/risks from summaries.
9. **Resume parse**: extract sections (experience, projects, skills, claims).
10. **Claim ↔ fact mapping**: for each resume claim, attempt grounding against project KB; store mapping with confidence + source refs.

All steps idempotent and re-runnable; intermediate state persisted in DB so jobs resume where they stopped.

### 3.3 QA generation pipeline (sharded + merged)

Input: `(user_id, project_id, position, level)`.
Strategy:
1. Build a **plan**: list of "topics" (modules, key decisions, resume claims, common patterns relevant to position+level). Plan is persisted.
2. For each topic, **batch-generate 5–10 Q&A** through the Gateway. Each batch:
   - Has its own job id and a **shard file** at `/var/openinterview/blobs/<user_id>/qa/<run_id>/shard_<n>.json`.
   - Written atomically (write tmp, fsync, rename).
   - Recorded as `committed` in `qa_runs` table once on disk.
3. After all topics done, a **merge step** loads all shards, deduplicates similar questions (embedding cosine threshold), normalizes metadata, and writes the canonical set into the `qa` table + Chroma collection `user_<id>_qa`.
4. If the run is interrupted, restart picks up uncommitted topics only.

### 3.4 QA entry schema (logical)

```
question:        str
model_answer:    str
follow_ups:      list[str]
position:        str
level:           enum(junior|mid|senior|staff|principal|tech_lead)
category:        enum(coding|system_design|ml|applied_ai|behavioral|project_deepdive)
grounded_refs:   list[{project_id, file, lines}]
difficulty:      int (1..5)
level_deltas:    map[level -> str]   # how a different level would answer
tags:            list[str]
source:          enum(private|common)
created_at:      datetime
version:         int
```

### 3.5 Evaluation rubric (Interviewer)

For each answer and at session end:
- **Technical correctness** (0–5)
- **Depth & tradeoff awareness** (0–5)
- **Communication clarity & structure** (0–5)
- **Tone / confidence** (0–5)  *(placeholder for v2 voice; v1 derived from text only — hedging, filler phrases, structure)*
- **Level-appropriateness** (gap vs. target level)

Output: structured `EvaluationEvent` written to episodic memory + a free-text coaching note.

### 3.6 Memory subsystem

Three layers, all per-user:

1. **Raw chat log** — append-only table `chat_messages` keyed by session.
2. **Episodic memory** — table `episodic_events`:
   - Session summary (mode, topics, length, outcome).
   - Interviewer evaluation events (rubric scores + notes).
3. **Semantic profile memory** — table `profile_facts` and a Chroma collection `user_<id>_profile`:
   - Structured fields: `strengths[]`, `weaknesses[]`, `communication_notes[]`, `goals[]`, `recommended_focus[]`.
   - Versioned: each distillation produces a new revision with provenance pointing at the episodic events that supported it.

**Distillation job** runs after every Interviewer session and on a daily cron:
- Load latest episodic events since last distillation.
- LLM pass produces a delta over current profile.
- Apply delta with conflict-resolution heuristics (more recent + higher-confidence wins).

**Mentor read flow**: chat history (last N messages) + retrieved profile facts (top-k via embedding of current question) + retrieved private/common KB chunks.

**Interviewer read flow**: profile facts (to choose weak-area questions) + project KB + selected QA bank.

### 3.7 GenAI Model Gateway

**API surface (internal):**
- `POST /v1/chat/completions` — OpenAI-shaped.
- `POST /v1/embeddings` — OpenAI-shaped.
- `POST /v1/admin/keys` — set/rotate admin keys (admin-only).
- `GET  /v1/usage` — usage records (filterable by user, model, time).

**Per-request flow:**
1. Authenticate caller (Core/Worker via service token + acting `user_id`).
2. Resolve credentials:
   - If user has BYO key for the requested logical model family, use it. Mode = `byo`.
   - Else use admin key for the resolved provider. Mode = `shared`.
3. Apply rate limits:
   - `byo` → none.
   - `shared` → tier-based (requests/min). Token caps **not** enforced in v1 but recorded.
4. Forward to OpenAI-compatible endpoint resolved by logical model name.
5. Record `gateway_usage_log` row: `user_id, mode, logical_model, provider, endpoint, prompt_tokens, completion_tokens, total_tokens, latency_ms, status, error?`.
6. Stream response back to caller.

**Config (admin-managed):**
- `models.yaml` — logical name → provider/endpoint/model id mapping, plus role (chat/embedding) and default.
- `tiers.yaml` — tier → rate limit mapping.

### 3.8 Voice-ready interfaces (v1 stubs)

- `MessageEnvelope { role, content_text, content_audio_ref? }` returned from chat endpoints.
- Frontend chat components consume the envelope; audio rendering is a no-op in v1.
- A future `STTProvider`/`TTSProvider` interface is reserved (`audio.py`) — v1 contains only the abstract types and a `NoopAdapter`.

### 3.9 Blob storage abstraction

All persistent file artifacts (uploaded projects, resumes, generated diagrams, QA shards, exports) go through a single `BlobStorage` interface. No part of the application reads or writes raw filesystem paths directly.

Interface (Python, conceptual):

```python
class BlobStorage(Protocol):
    async def put(self, logical_path: str, data: bytes | IO[bytes],
                  content_type: str | None = None) -> BlobRef: ...
    async def get(self, logical_path: str) -> bytes: ...
    async def open_read(self, logical_path: str) -> IO[bytes]: ...
    async def open_write(self, logical_path: str) -> IO[bytes]: ...
    async def delete(self, logical_path: str) -> None: ...
    async def list(self, prefix: str) -> list[BlobRef]: ...
    async def exists(self, logical_path: str) -> bool: ...
    async def signed_url(self, logical_path: str, ttl_s: int) -> str: ...
```

Backends shipped in v1: `LocalFSBlobStorage`, `S3BlobStorage`, `AzureBlobStorage`, `GCSBlobStorage`. A factory `make_blob_storage(config)` returns the configured one.

Tenant safety: every call site passes `user_id` and uses helpers like `paths.user_project_source(user_id, project_id, rel_path)` so cross-user paths are impossible to construct by accident.

Atomic writes: implementations expose `open_write` whose context manager finalizes via tmp+rename (local) or single-call PUT (cloud).

### 3.10 Configuration & environment

The application reads config from env vars (twelve-factor) backed by a typed settings model (Pydantic `BaseSettings`). A single `Config` object is built once at startup and injected via DI; modules never read env vars directly.

Key env vars (subset):

```
OPENINTERVIEW_ENV=local|server
OPENINTERVIEW_DATA_DIR=/abs/path             # used when STORAGE_BACKEND=local
STORAGE_BACKEND=local|s3|azure|gcs
S3_BUCKET=...
S3_PREFIX=openinterview
S3_REGION=...
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY    # or use IAM role
AZURE_STORAGE_ACCOUNT=...
AZURE_STORAGE_CONTAINER=...
AZURE_STORAGE_SAS_OR_KEY=...
GCS_BUCKET=...
GCS_PREFIX=openinterview

DATABASE_URL=postgresql+asyncpg://...
VECTOR_BACKEND=chroma
CHROMA_URL=http://chroma:8000

GATEWAY_URL=http://gateway:9000
GATEWAY_SERVICE_TOKEN=...

OPENINTERVIEW_MASTER_KEY=...                 # AES-GCM master key for at-rest secrets
JWT_SECRET=...
JWT_ACCESS_TTL_S=900
JWT_REFRESH_TTL_S=2592000

WORKER_BACKEND=arq                           # arq | rq | celery (one chosen for v1)
REDIS_URL=redis://redis:6379/0
```

Profiles ship as files: `config/env.local.example`, `config/env.server.example`. Switching from local-first to server-hosted is purely a config change — no code changes.

---

## 4. Data Models

### 4.1 PostgreSQL tables (logical)

```
users(id, email, password_hash, display_name, tier, is_admin, created_at)
user_api_keys(id, user_id, provider, encrypted_key, label, created_at)
projects(id, user_id, name, source_type, source_uri, status, created_at)
resumes(id, user_id, original_filename, parsed_json, created_at)
target_selections(id, user_id, position, level, project_ids[], created_at)

ingest_runs(id, user_id, project_id, status, step, error?, started_at, finished_at)
qa_runs(id, user_id, project_id, position, level, status, plan_json, started_at, finished_at)
qa_shards(id, qa_run_id, topic, path, committed, created_at)
qa(id, user_id, project_id, position, level, category, question, model_answer,
   follow_ups_json, grounded_refs_json, difficulty, level_deltas_json, tags, source,
   version, created_at)

chat_sessions(id, user_id, mode, position?, level?, started_at, ended_at?)
chat_messages(id, session_id, role, content, audio_ref?, created_at)

episodic_events(id, user_id, session_id?, kind, payload_json, created_at)
profile_facts(id, user_id, kind, key, value, confidence, source_event_ids[], revision, created_at)

common_kb_items(id, source, category, position?, level?, question, model_answer,
                refs_json, version, created_at)

gateway_usage_log(id, user_id, mode, logical_model, provider, endpoint,
                  prompt_tokens, completion_tokens, total_tokens, latency_ms, status, error?, created_at)

tiers(name, rate_limit_rpm, ...)
```

### 4.2 Vector collections (Chroma)

- `user_<uid>_project_<pid>` — code & doc chunks
- `user_<uid>_qa` — generated QA
- `user_<uid>_profile` — semantic profile facts
- `common_kb_<source>` — applied_ai_questions, system_design_primer

### 4.3 Blob storage layout (logical, backend-agnostic)

Blobs are addressed by **logical paths** that the application code never resolves to an OS path directly. A `BlobStorage` interface (see §3.9) is responsible for turning a logical path into an actual location on the configured backend (local FS / S3 / Azure Blob / GCS / etc.).

Logical paths:

```
users/<user_id>/projects/<project_id>/source/...
users/<user_id>/projects/<project_id>/diagrams/*.mmd
users/<user_id>/qa/<qa_run_id>/shard_*.json
users/<user_id>/resumes/<resume_id>/original.<ext>
users/<user_id>/exports/<export_id>.zip
```

Backend resolution is configured via env (see §3.10):
- `local` → `${OPENINTERVIEW_DATA_DIR}/users/<user_id>/...`
- `s3` → `s3://<bucket>/<prefix>/users/<user_id>/...`
- `azure` → `https://<account>.blob.core.windows.net/<container>/<prefix>/users/<user_id>/...`
- `gcs` → `gs://<bucket>/<prefix>/users/<user_id>/...`

Application code never hardcodes `/var/...` or any provider URL.

---

## 5. Sequence Diagrams (textual)

### 5.1 Onboarding & ingestion

```
User -> WebUI: upload project + resume, pick position(s)+level(s)
WebUI -> Core: POST /projects, /resumes, /target-selections
Core -> DB: create rows, enqueue ingest_run
Worker -> Core: pull job
Worker -> Gateway: embed chunks, summarize files/modules/project
Worker -> DB: write summaries, decisions, resume parse, claim mapping
Worker -> Core: mark ingest_run done
Core -> WebUI: progress stream (SSE) until done
```

### 5.2 QA generation (sharded)

```
Core -> DB: enqueue qa_run with plan
Worker: for each topic in plan:
  Worker -> Gateway: generate batch of 5–10 Q&A
  Worker -> FS: write shard_n.json (atomic)
  Worker -> DB: mark shard committed
Worker (merge): load all shards -> dedupe -> write to qa table + vector store
Worker -> DB: mark qa_run done
```

### 5.3 Mentor turn

```
WebUI -> Core: POST /mentor/sessions/{id}/messages { text }
Core -> DB: append user message
Core -> Memory: retrieve top profile facts + recent episodic summaries
Core -> KB: retrieve top private & common chunks
Core -> Gateway: chat completion with assembled context
Gateway -> Provider -> Gateway -> Core: response + usage
Core -> DB: append assistant message; log usage
Core -> WebUI: stream tokens
```

### 5.4 Interviewer session + evaluation

```
WebUI -> Core: start interviewer session (position, level)
Core: pick question plan from QA bank biased by profile weaknesses
loop per question:
  Core -> WebUI: question
  WebUI -> Core: answer
  Core -> Gateway: optional probe / follow-up generation
end loop
Core -> Gateway: end-of-session evaluation against rubric
Core -> DB: write episodic_event(kind=evaluation, payload=rubric+notes)
Core -> Worker: enqueue distillation job
Worker -> Gateway: distill profile delta from new events
Worker -> DB: write profile_facts revision
```

### 5.5 Gateway request

```
Caller -> Gateway: /v1/chat/completions { user_id, logical_model, msgs }
Gateway: resolve credentials (BYO vs shared)
Gateway: rate-limit check (skip for BYO)
Gateway -> Provider: forward
Provider -> Gateway: response (+ usage)
Gateway -> DB: insert gateway_usage_log row
Gateway -> Caller: response
```

---

## 6. REST API Surface (v1 sketch)

All under `/api/v1`, JWT-auth except `/auth/*`.

```
POST   /auth/register
POST   /auth/login
POST   /auth/refresh

GET    /me
POST   /me/api-keys
DELETE /me/api-keys/{id}

POST   /projects              (multipart or git URL)
GET    /projects
GET    /projects/{id}
POST   /projects/{id}/reingest

POST   /resumes
GET    /resumes/{id}

POST   /target-selections
GET    /target-selections

POST   /qa/runs               (kicks off generation)
GET    /qa/runs/{id}
GET    /qa?position=&level=&project_id=

POST   /mentor/sessions
POST   /mentor/sessions/{id}/messages   (SSE stream)
GET    /mentor/sessions
GET    /mentor/sessions/{id}/messages

POST   /interviewer/sessions
POST   /interviewer/sessions/{id}/turns (SSE stream)
POST   /interviewer/sessions/{id}/end   (triggers evaluation)
GET    /interviewer/sessions/{id}/evaluation

GET    /memory/profile
GET    /memory/episodic

POST   /me/wipe
POST   /me/export

# Admin
GET    /admin/users
PATCH  /admin/users/{id}
GET    /admin/gateway/usage
POST   /admin/common-kb/refresh
```

Gateway (internal, separate port):
```
POST /v1/chat/completions
POST /v1/embeddings
POST /v1/admin/keys
GET  /v1/usage
```

---

## 7. Repository / Directory Layout

Top-level split is **frontend** vs **backend**. User data is **never** stored under the repo or the app code; it is referenced only by logical paths and resolved by the configured `BlobStorage` backend (see §3.9). For local development a separate data directory (outside the repo) is used and is configured via `OPENINTERVIEW_DATA_DIR`.

```
open-interview/
  docs/
    requirements-and-system-design.md
    COMMON_KB_INVENTORY.md
    CHANGELOG.md

  frontend/                          # all UI code
    app/                             # React + Vite SPA
      src/
        pages/
        components/
        features/
          auth/
          onboarding/
          mentor/
          interviewer/
          memory/
          admin/
        api/                         # typed API client
        lib/
      index.html
      vite.config.ts
      package.json
    tests/

  backend/
    services/
      core/                          # FastAPI core API
        src/openinterview_core/
          api/                       # thin routers; only HTTP concerns
            v1/
              auth.py
              projects.py
              resumes.py
              targets.py
              qa.py
              mentor.py
              interviewer.py
              memory.py
              admin.py
          domain/                    # pure business logic, no I/O
            projects/
            resumes/
            targets/
            qa/                      # planner, dedupe, level deltas
            mentor/                  # agent policy, prompt builders
            interviewer/             # session policy, rubric
            memory/                  # raw / episodic / semantic models
            kb/                      # retriever interfaces
          infra/                     # adapters / I/O
            db/                      # SQLAlchemy models, repositories
            vector/                  # Chroma adapter (behind interface)
            blob/                    # BlobStorage interface + factory
              local_fs.py
              s3.py
              azure.py
              gcs.py
            gateway_client/          # HTTP client to GenAI Gateway
            agents/                  # LangGraph wiring (mentor, interviewer)
            audio/                   # v1 stubs (NoopSTT/TTS)
          config/                    # pydantic settings, env loading
          security/                  # auth, hashing, encryption, isolation guards
          common/                    # logging, errors, ids, time
        tests/
          unit/
          integration/
          isolation/                 # per-tenant access tests

      gateway/                       # GenAI Model Gateway (separate service)
        src/openinterview_gateway/
          api/
            v1/
              chat.py
              embeddings.py
              admin_keys.py
              usage.py
          domain/
            routing/                 # logical-model -> provider resolver
            rate_limit/              # tier-based limiter
            usage/                   # accounting model
            keys/                    # vault interface
          infra/
            providers/               # OpenAI-compatible adapters
            db/                      # usage_log, keys storage
            secrets/                 # encryption helpers
          config/
          common/
        tests/

      workers/                       # background jobs
        src/openinterview_workers/
          jobs/
            ingest_project.py
            ingest_resume.py
            qa_generate.py           # plan -> shard -> commit
            qa_merge.py              # shards -> canonical
            distill_profile.py
          adapters/                  # reuse core's blob/db/gateway clients
          common/
        tests/

    libs/                            # shared backend libraries (versioned)
      openinterview_schemas/         # pydantic DTOs shared by core + gateway + workers
      openinterview_storage/         # BlobStorage interface + impls (used by core+workers)
      openinterview_db/              # shared SQLAlchemy base + migrations
      openinterview_logging/

  infra/
    docker-compose.local.yml         # local dev: postgres, redis, chroma, core, gateway, web
    docker-compose.server.yml        # server profile: same services + cloud blob, no local data dir
    Dockerfile.core
    Dockerfile.gateway
    Dockerfile.workers
    Dockerfile.web
    postgres/
    chroma/

  config/
    env.local.example                # STORAGE_BACKEND=local + OPENINTERVIEW_DATA_DIR
    env.server.example               # STORAGE_BACKEND=s3 (or azure/gcs)
    models.yaml                      # logical model -> provider/endpoint
    tiers.yaml                       # tier -> rate limits

  scripts/
    seed_common_kb.py
    refresh_common_kb.py
    create_admin.py
    isolation_smoke_test.py
```

User-uploaded data lives **outside** the repo:

- `local` mode: under `${OPENINTERVIEW_DATA_DIR}` (e.g., `~/.openinterview/data` or `/var/openinterview`), containing only the logical tree from §4.3.
- `server` mode: in the configured cloud bucket; the local data dir is unused.

### 7.1 Implementation guidelines

These rules are part of the contract — code reviews enforce them.

- **Single responsibility**: routers contain only HTTP wiring; business logic lives in `domain/`; I/O lives in `infra/`. No direct DB access from routers.
- **Function size**: keep functions short (target ≤ 40 lines, ≤ 3 levels of nesting). Prefer composition over long procedural blocks.
- **Module shape**: each domain module exposes a small public API (`__all__`); internals are private.
- **Interfaces over implementations**: `BlobStorage`, `VectorStore`, `LLMClient`, `Embedder`, `KeyVault`, `RateLimiter`, `Memory{Raw,Episodic,Semantic}Store` are abstract; concrete classes are injected via the config-driven factory.
- **Config injection**: a single `Config` is built at startup; modules never call `os.environ` directly.
- **Error handling**: typed exceptions per domain; an HTTP error mapper at the API edge.
- **Testing**: every domain module has unit tests with fakes; per-tenant isolation tests run in CI.
- **Naming**: APIs and functions read as actions on domain nouns (`projects.ingest`, `qa.generate_batch`, `memory.episodic.append`).
- **No god-functions**: an LLM-driven step that does N things must be broken into N functions, each independently testable and replayable.

---

## 8. Security & Multi-tenant Isolation

- All API endpoints require JWT; middleware injects `current_user`.
- Every DB query that returns user-owned rows MUST filter by `user_id`. Enforced via repository layer + a test that scans for raw SQL violations.
- Vector collections are namespaced per user; no shared collection contains private content.
- Filesystem blobs are written under `/var/openinterview/blobs/<user_id>/`; access functions take `user_id` and refuse cross-user paths.
- Secrets at rest:
  - Server master key from env (`OPENINTERVIEW_MASTER_KEY`).
  - User BYO API keys encrypted with AES-GCM using a key derived from master key + user salt.
  - JWT signing secret in env.
- Passwords hashed with argon2id.
- Admin endpoints gated by `is_admin`.
- Gateway requires a service-to-service token from Core/Workers and the acting `user_id`; logs both.
- Automated test: User A's JWT cannot read any of User B's resources; cannot trigger jobs on User B's projects.

---

## 9. Common KB Inventory & Sourcing Plan

A separate file `docs/COMMON_KB_INVENTORY.md` will be created at implementation time with the following structure (placeholder content here):

**Included in v1**
- `applied_ai_questions` — curated list (open-source, permissively licensed sources only) of LLM/RAG/agent/eval questions; **answers are model-generated by us**.
- `system_design_primer` — question prompts inspired by widely-cited system design topics; **answers are model-generated by us**, no copyrighted solutions stored.

**Explicitly NOT in v1**
- `leetcode_topics` — deferred (licensing).
- `ml_interview_questions` (general ML) — deferred.
- `behavioral_star_bank` — deferred.

Refresh: admin runs `scripts/refresh_common_kb.py`; produces a new version row in `common_kb_items`.

---

## 10. Voice Readiness (v1 = text-only)

- Chat envelope schema includes optional `content_audio_ref` field (always null in v1).
- `audio/` package contains:
  - `STTProvider` abstract interface.
  - `TTSProvider` abstract interface.
  - `NoopSTT`, `NoopTTS` (default).
- Frontend chat components ignore audio fields when null. Adding a real provider in v2 requires only a new adapter + a UI toggle, with no schema migration.

---

## 11. Risks & Open Items

- **Project size blowup**: very large monorepos could exceed embedding budgets. Mitigation: per-project ignore rules + per-folder summary rollups + per-language size caps.
- **QA quality drift**: model answers may be wrong. Mitigation: model_answer is regeneratable; users can edit/flag; Mentor cross-checks against grounded refs.
- **Memory bloat**: profile memory could become noisy. Mitigation: distillation reconciles conflicts and ages out unused facts.
- **Gateway as a SPOF**: but it is required by design for centralized control. Mitigation: it is stateless except for the usage log; a restart loses no in-flight requests.
- **Voice in v2**: latency budget will need re-design once added.

---

## 12. Build Plan (no coding until approved)

Milestones (rough order):
1. **M0 — Skeletons**: Docker Compose, Postgres, Chroma, Core, Gateway, Web shell, auth, healthchecks.
2. **M1 — Gateway**: providers, rate limits, usage logging, BYO-key path.
3. **M2 — Project & resume ingestion**: upload, tree-sitter chunking, hierarchical summaries, diagrams, claim mapping.
4. **M3 — QA generation**: planner, sharded generator, merger, dedupe.
5. **M4 — Mentor**: LangGraph agent + retrieval + memory read.
6. **M5 — Interviewer**: LangGraph agent + rubric evaluator + episodic write.
7. **M6 — Distillation & profile memory**: job + Mentor consumes profile.
8. **M7 — Common KB**: applied_ai + system_design_primer; refresh script.
9. **M8 — Hardening**: per-tenant isolation tests, export/wipe, observability, MVP acceptance run-through.

Each milestone ends with a runnable demo and tests.

---

## 13. Approval

This document is the contract for v1. Implementation will begin **only after explicit approval**. Any change after approval will be tracked in `docs/CHANGELOG.md`.
