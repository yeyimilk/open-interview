<div align="center">

# Open Interview

**Self-hosted, multi-user interview prep grounded in *your* code.**

Upload a project + resume → get a personalized mentor and interviewer that
read your repo, ground every claim in real code, and remember what you've
practiced. Bring your own LLM key, run locally, and keep your data on your
machine.

![status](https://img.shields.io/badge/status-alpha-orange)
![license](https://img.shields.io/badge/license-Apache%202.0-blue)
![python](https://img.shields.io/badge/python-3.11+-3776ab?logo=python&logoColor=white)
![react](https://img.shields.io/badge/react-18-61dafb?logo=react&logoColor=white)
![fastapi](https://img.shields.io/badge/fastapi-async-009688?logo=fastapi&logoColor=white)

[Quickstart](#-quickstart) ·
[Features](#-features) ·
[Architecture](#-architecture) ·
[Configuration](#-configuration) ·
[Roadmap](#-roadmap) ·
[Contributing](#-contributing)

</div>

---

## ✨ Why Open Interview?

Most interview-prep tools throw generic LeetCode questions at you. Real
interviews are about **your** projects, **your** resume, and the trade-offs
**you** actually made.

Open Interview turns your codebase into the curriculum:

- 📂 **Reads your repo.** A LangGraph mentor browses files, runs `grep`, and
  reads source — Cursor / Claude Code style — so answers cite real files.
- 📝 **Grounds your resume.** Claims are matched against project evidence so
  the interviewer can probe what's actually true.
- 🧠 **Remembers everything.** Three layers of memory (working / episodic /
  long-term) keep gaps and strengths sticky across sessions.
- 🎙️ **Voice practice.** Talk through answers with recorded STT and live
  interview audio built in.
- 🔐 **Local-first.** Bring your own OpenAI / Anthropic / Ollama / vLLM key.
  Multi-tenant from day one, your data never leaves your machine.

---

## 🚀 Quickstart

```bash
git clone https://github.com/your-org/open-interview.git
cd open-interview
make setup                          # venv, editable installs, speaker deps, npm install
cp config/env.dev.example .env

make infra        # postgres + redis + chroma in Docker (background)
make all          # core + gateway + realtime + workers + web  (overmind / honcho)
```

| Surface       | URL                                          |
| ------------- | -------------------------------------------- |
| Web app       | <http://localhost:5173>                      |
| Core API docs | <http://localhost:8000/docs>                 |
| Gateway docs  | <http://localhost:9100/docs>                 |

> **Heads up:** `make all` requires a process manager
> (`brew install overmind` recommended, or `pip install honcho`).
> Don't have one? Run each service in its own terminal —
> `make core`, `make gateway`, `make realtime`, `make workers`, `make web`.

Add your provider key in **Settings → API keys** once the UI is up. From
there, upload a project zip + resume, then start a Mentor or Interviewer
session.

Live voice mode uses OpenAI Realtime transcription plus local speaker
verification. If an existing `.venv` predates this feature, run
`make setup-speaker` once before starting `make realtime` or `make all`.

---

## 🎯 Features

<table>
<tr>
<td width="50%" valign="top">

### 🧑‍🏫 Mentor mode
Conversational coach that has *read your code*. The agent uses
read-only tools — `list_dir`, `read_file`, `grep`, `tree` — and
shows its work in a collapsible trace next to every answer.

</td>
<td width="50%" valign="top">

### 🎤 Interviewer mode
Adaptive interviewer that asks questions sourced from your own
project. Per-turn evaluation, gap-aware question picker, and a
final rubric with strengths, weaknesses, and suggested practice.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 📚 Grounded QA generation
Per-(project × position × level) bank of 25 evidence-backed
questions: planner → 7 sharded generators → merger.
Auto-generates on ingest, regeneratable on demand.

</td>
<td width="50%" valign="top">

### 🧠 Three layers of memory
Working (last-N msgs), episodic (per-session summary +
entities), long-term (per-user vector store of gaps,
strengths, preferences). Distilled at session end.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🔌 BYO model gateway
OpenAI-compatible internal gateway routes logical models
(`chat-fast`, `chat-strong`, `embed-default`, `stt-default`,
`voice-analysis-default`) to any provider — OpenAI, Anthropic,
Ollama, vLLM, LM Studio, OpenRouter, Together, Groq, Fireworks,
DeepSeek. **Per-user overrides** in Settings → Models let each
user pick their own provider/model per role (chat, embeddings,
STT, voice analysis) with live `/v1/models` discovery and a
one-click Test button. BYO mode = no rate limits.

</td>
<td width="50%" valign="top">

### 🎙️ Voice input & delivery scoring
Recorded voice answers use browser-native `MediaRecorder` →
multipart upload → Whisper / `gpt-4o-mini-transcribe`. Live
interviewer mode streams continuous 24 kHz PCM through the
OpenInterview realtime gateway for OpenAI Realtime transcription,
server-side turn aggregation, and session-local speaker verification.
Accepted live turns reuse the same interviewer agent and persistence
flow as text turns.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 📦 Project ingestion
Zip upload → AST chunking → embeddings → hierarchical
summaries → Mermaid diagrams. Files browsable, summaries
queryable, all evidence linkable.

</td>
<td width="50%" valign="top">

### 📄 Resume grounding
PDF / docx / md upload. Parsed into identity, skills,
experience timeline, projects, and **claims** — each claim
linked to project code with confidence scores.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 💬 WhatsApp plugin
Pair your **personal** number (no business API) by scanning
a QR in **Settings → Messaging**. From your phone:
`/chat`, `/mentor`, `/interview`, `/projects`, `/resumes`,
`/sessions`, `/resume-session <prefix>`. Per-recipient rate
limiting + echo suppression keep group chats sane.

</td>
<td width="50%" valign="top">

### 🧩 Pluggable channels
Channel SDK modeled after openclaw. Adding WeChat / Telegram /
Slack is a new `plugins/<id>/` directory — no kernel
changes. Manifest discovery, capability flags, kernel-
mediated delivery with chunking + dedup.

</td>
</tr>
</table>

---

## 🏗️ Architecture

```
┌──────────────┐         ┌─────────────────────────────────────┐
│  React SPA   │         │  WhatsApp (your personal number)    │
└──────┬───────┘         └────────────┬────────────────────────┘
       │ HTTPS + JWT                  │ Baileys (WhatsApp Web)
       │                              ▼
       │              ┌────────────────────────────────────────┐
       │              │ whatsapp_bridge (Node + Fastify)       │
       │              │ • multi-account socket manager         │
       │              │ • echo cache · HMAC webhook poster     │
       │              └─────────────────┬──────────────────────┘
       │                                │ HTTP + HMAC
       ▼                                ▼
┌──────────────────────────────────────────────────────────┐
│                 FastAPI Core API                         │
│                                                          │
│  api/    ─ auth, projects, resumes, qa, mentor,          │
│            interviewer, audio, messaging                 │
│  domain/ ─ projects (chunker, embedder, summarizer)      │
│            resumes (parser, claim grounder)              │
│            qa (planner, shard generator, merger)         │
│            mentor (LangGraph + ProjectFs tools)          │
│            interviewer (LangGraph + picker + evaluator)  │
│            memory (recall + distiller)                   │
│            messengers (kernel · sdk · plugins/whatsapp)  │
│  infra/  ─ Postgres · Redis · Chroma · BlobStorage       │
└──────┬─────────────┬───────────────┬─────────────────────┘
       │             │               │
       ▼             ▼               ▼
┌─────────────┐ ┌─────────┐ ┌──────────────────┐
│ GenAI       │ │  arq    │ │ Vector Store     │
│ Gateway     │ │ workers │ │ (Chroma /        │
│             │ │         │ │  in-memory)      │
│ • chat      │ └─────────┘ └──────────────────┘
│ • chat/stream
│ • embed
│ • transcribe
│ • realtime session minting
│ • rate-limit + usage logs
└──────┬──────┘
       │ OpenAI-compatible
       ▼
┌─────────────────────────────────────────────────────────┐
│ OpenAI · Anthropic (adapter) · Ollama · vLLM · OpenRouter │
└─────────────────────────────────────────────────────────┘
```

Live interviewer audio runs through a separate realtime gateway:

```mermaid
sequenceDiagram
    participant Browser as React live chat
    participant RT as realtime_gateway
    participant GW as GenAI gateway
    participant OA as OpenAI Realtime
    participant Core as Core interviewer

    Browser->>RT: WS hello + config + PCM16 chunks
    RT->>Browser: calibration_required
    Browser->>RT: calibration_start / PCM16 / calibration_commit
    RT->>RT: enroll session-local speaker profile
    RT->>GW: mint realtime transcription session
    GW->>OA: POST /realtime/transcription_sessions
    OA-->>GW: ephemeral client_secret
    GW-->>RT: ws_url + client_secret
    RT->>OA: provider WS, append PCM16
    OA-->>RT: speech_started / speech_stopped / transcript completed
    RT->>RT: defer commit while speech or transcript items are outstanding
    RT->>RT: speaker + confidence gates
    RT->>Core: accepted primary-speaker transcript
    Core-->>RT: interviewer SSE tokens
    RT-->>Browser: final_transcript + assistant_token + assistant_done
```

### Repository layout

```
open-interview/
├── frontend/app/              # Vite + React SPA
├── backend/
│   ├── services/
│   │   ├── core/              # FastAPI app (api / domain / infra)
│   │   ├── gateway/           # GenAI gateway (provider router + rate limiter)
│   │   ├── realtime_gateway/  # live audio WS, Realtime STT, speaker gate
│   │   ├── workers/           # arq background jobs
│   │   └── whatsapp_bridge/   # Node sidecar (Fastify + Baileys), port 9300
│   └── libs/                  # shared schemas, db models, storage, logging
├── infra/                     # Docker Compose, Dockerfiles
├── config/                    # models.yaml, tiers.yaml, env profiles
├── docs/                      # design doc + TODO.md
├── scripts/                   # one-off scripts
└── data/                      # gitignored: blob storage in dev
```

### Tech stack

| Layer | Tools |
| ----- | ----- |
| Frontend | React 18, Vite, TypeScript, Tailwind, shadcn/ui, lucide-react, react-markdown, react-router |
| Core API | FastAPI, SQLAlchemy 2 (async), pydantic v2, LangGraph, httpx, argon2, PyJWT |
| Realtime gateway | FastAPI WebSockets, OpenAI Realtime transcription, SpeechBrain ECAPA speaker verification |
| Persistence | Postgres (prod) / SQLite (tests), Redis, Chroma vector DB |
| Workers | arq (Redis-backed task queue) |
| Messenger bridge | Node 20, TypeScript, Fastify, Baileys (`@whiskeysockets/baileys`), vitest |
| LLM | OpenAI-compatible — gpt-4o, gpt-4o-mini, gpt-4o-mini-transcribe, text-embedding-3-small (defaults; override in `config/models.yaml`) |
| Tooling | pytest, ruff, mypy, Docker Compose, overmind / honcho |

---

## ⚙️ Configuration

Environment lives in `.env` (start from `config/env.dev.example`). Highlights:

```bash
# Database / cache
DATABASE_URL=postgresql+asyncpg://openinterview:openinterview@localhost:55432/openinterview
REDIS_URL=redis://localhost:56379/0
CHROMA_URL=http://localhost:8001

# Auth
JWT_SECRET=change-me-32-bytes-min
JWT_ACCESS_TTL_S=900
JWT_REFRESH_TTL_S=2592000

# Encryption (AES-GCM at rest for user keys)
OPENINTERVIEW_MASTER_KEY=change-me-32-bytes-min

# Internal gateway
GATEWAY_URL=http://localhost:9100
GATEWAY_SERVICE_TOKEN=change-me-internal-only

# Live interviewer audio
REALTIME_PUBLIC_URL=ws://localhost:9200/ws/interview
OPENINTERVIEW_REALTIME_SECRET=change-me-32-bytes-min
REALTIME_INTERNAL_TOKEN=change-me-internal-only
REALTIME_MAX_TURN_SECONDS=90
REALTIME_TRANSCRIPTION_MODEL=gpt-4o-transcribe
REALTIME_NOISE_REDUCTION=near_field
REALTIME_TURN_DETECTION=semantic_vad
REALTIME_SPEAKER_VERIFIER_BACKEND=speechbrain
REALTIME_SPEAKER_THRESHOLD=0.25
REALTIME_CALIBRATION_SECONDS=5.0
REALTIME_MIN_TURN_AUDIO_MS=300
REALTIME_MIN_TRANSCRIPT_CONFIDENCE=0.35
REALTIME_VAD_EAGERNESS=low
REALTIME_TURN_COMMIT_DELAY_MS=1200
# Optional local-only WAV/JSON dumps for live-audio debugging.
REALTIME_DEBUG_AUDIO_DIR=
```

### Model routing (`config/models.yaml`)

Logical names decouple agent code from providers:

```yaml
chat:
  default: chat-strong
  models:
    chat-strong: { provider: openai, endpoint: https://api.openai.com/v1, model_id: gpt-4o }
    chat-fast:   { provider: openai, endpoint: https://api.openai.com/v1, model_id: gpt-4o-mini }
    chat-local:  { provider: ollama, endpoint: http://ollama:11434/v1,    model_id: qwen2.5-coder:32b }

embedding:
  default: embed-default
  models:
    embed-default: { provider: openai, endpoint: https://api.openai.com/v1, model_id: text-embedding-3-small }

transcription:
  default: stt-default
  models:
    stt-default:  { provider: openai, endpoint: https://api.openai.com/v1, model_id: gpt-4o-mini-transcribe }
    stt-whisper:  { provider: openai, endpoint: https://api.openai.com/v1, model_id: whisper-1 }

voice-analysis:
  default: voice-analysis-default
  models:
    voice-analysis-default: { provider: openai, endpoint: https://api.openai.com/v1, model_id: gpt-4o-audio-preview }
```

Swap any line for your own provider — Ollama, vLLM, OpenRouter, Together —
as long as it speaks the OpenAI API.

#### Per-user overrides (Settings → Models)

`models.yaml` is the **server-wide fallback**. Any user can override it
per role from the UI:

| Role            | Used by                                        | Discovery       |
| --------------- | ---------------------------------------------- | --------------- |
| Chat / LLM      | Mentor, mock interviewer, project explainer    | live `/v1/models` |
| Embeddings      | Project search, long-term memory recall        | live `/v1/models` |
| Transcription   | Speech-to-text in voice mode                   | live `/v1/models` |
| Voice analysis  | Multimodal delivery scoring                    | live `/v1/models` |

Picks are stored in `user_model_preferences` and transparently injected
into every gateway call via a `ProviderOverride`, so the agents stay
unaware. The Settings UI filters the catalogue to recommended models
per role (with a "Show all" escape hatch), preselects a sane default
for the picked provider, and gates Save behind a Test round-trip.

Reasoning models (OpenAI o-series, gpt-5) are detected automatically:
the gateway sends `max_completion_tokens` (with a high floor for hidden
reasoning tokens) instead of `max_tokens`, drops unsupported `temperature`,
and auto-retries once on the well-known `unsupported parameter` and
`output limit reached` errors.

---

## 🧪 Tests

```bash
make test                 # full backend suite
.venv/bin/python -m pytest backend/services/core/tests -q
cd frontend/app && npx tsc --noEmit && npx vite build
```

Current coverage includes focused suites for core agent flows, gateway model
routing and realtime session minting, realtime live-session turn aggregation
and speaker gating, and a typecheck-clean Vite build.

---

## 🗺️ Roadmap

| Milestone | Status | What |
| --------- | :----: | ---- |
| **M0** Foundations | ✅ | FastAPI skeleton, multi-tenant auth (argon2 + JWT + refresh), per-user data isolation |
| **M1** GenAI Gateway | ✅ | OpenAI-compatible provider, BYO + shared modes, rate limiting, usage logging |
| **M2** Ingestion | ✅ | Project zip → chunk → embed → summarize → diagram; resume parse → claim ground |
| **M3** QA generation | ✅ | Planner → 7 sharded generators → merger; auto on ingest, regenerable |
| **M4** Mentor mode | ✅ | LangGraph + 3-layer memory + ProjectFs tools (`list_dir` / `read_file` / `grep` / `tree`) |
| **M5** Interviewer mode | ✅ | Gap-aware picker, per-turn eval, final rubric, evaluation page |
| **M6** Memory | ✅ | Working / episodic / long-term, distilled at session end, vector-recalled |
| **Audio** | ✅ | Voice input in chat + multimodal delivery scoring rolled into evaluation |
| **M7** Messenger SDK | ✅ | Plugin SDK + WhatsApp via Baileys sidecar (groups; commands; rate-limit; echo-suppression) |
| **M8** Common KB | 🚧 | Applied-AI question bank + system-design primer seeds |
| **M9** Per-user model picks | ✅ | Settings → Models with live `/v1/models` discovery, per-role override, Test before Save; reasoning-model param auto-translation |
| **M10** Public resources | 🚧 | LeetCode-tagged questions, system design primer, Designing Data-Intensive Apps notes — see [`docs/TODO.md`](docs/TODO.md) |
| **M11** WhatsApp DMs | 🚧 | Self-DM and direct-message inbound; currently surfaced as "Unavailable" — see [`docs/TODO.md`](docs/TODO.md) |
| **M12** WeChat | 🚧 | Same SDK; new plugin — see [`docs/TODO.md`](docs/TODO.md) |
| **M13** Hardening | 🚧 | Observability, export / wipe, real arq offload of QA generation |

---

## 🤝 Contributing

This is a personal/learning project at the moment. Issues, PRs, and design
discussions are very welcome — see
[`docs/requirements-and-system-design.md`](docs/requirements-and-system-design.md)
for the full spec before opening a substantive PR.

```bash
make setup       # one-time
make test        # before pushing
make fmt         # ruff (placeholder)
```

Coding conventions: clean architecture (api / domain / infra), interfaces
over implementations, small modules, tests next to the thing they test.

---

## 📜 License

Apache 2.0. The license file still needs to be added before distribution.

---

<div align="center">
<sub>Made with ☕ and a stubborn belief that interviews should reward the work you actually did.</sub>
</div>
