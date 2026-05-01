<div align="center">

# Open Interview

**Self-hosted, multi-user interview prep grounded in *your* code.**

Upload a project + resume → get a personalized mentor and interviewer that
read your repo, ground every claim in real code, and remember what you've
practiced. Bring your own LLM key — runs locally, your data stays on your box.

[![status](https://img.shields.io/badge/status-alpha-orange)]()
[![license](https://img.shields.io/badge/license-Apache%202.0-blue)]()
[![python](https://img.shields.io/badge/python-3.11+-3776ab?logo=python&logoColor=white)]()
[![react](https://img.shields.io/badge/react-18-61dafb?logo=react&logoColor=white)]()
[![fastapi](https://img.shields.io/badge/fastapi-async-009688?logo=fastapi&logoColor=white)]()

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
  reads source — Cursor / Claude Code style — so answers cite real lines.
- 📝 **Grounds your resume.** Claims are matched against project evidence so
  the interviewer can probe what's actually true.
- 🧠 **Remembers everything.** Three layers of memory (working / episodic /
  long-term) keep gaps and strengths sticky across sessions.
- 🎙️ **Voice in.** Talk through your answers — Whisper-class transcription
  baked in.
- 🔐 **Local-first.** Bring your own OpenAI / Anthropic / Ollama / vLLM key.
  Multi-tenant from day one, your data never leaves your machine.

---

## 🚀 Quickstart

```bash
git clone https://github.com/your-org/open-interview.git
cd open-interview
make setup                          # venv, editable installs, npm install
cp config/env.dev.example .env

make infra        # postgres + redis + chroma in Docker (background)
make all          # core + gateway + workers + web  (overmind / honcho)
```

| Surface       | URL                                          |
| ------------- | -------------------------------------------- |
| Web app       | <http://localhost:5173>                      |
| Core API docs | <http://localhost:8000/docs>                 |
| Gateway docs  | <http://localhost:9100/docs>                 |

> **Heads up:** `make all` requires a process manager
> (`brew install overmind` recommended, or `pip install honcho`).
> Don't have one? Run each service in its own terminal —
> `make core`, `make gateway`, `make workers`, `make web`.

Add your provider key in **Settings → API keys** once the UI is up. From
there, upload a project zip + resume, then start a Mentor or Interviewer
session.

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
(`chat-fast`, `chat-strong`, `embed-default`, `stt-default`) to
any provider — OpenAI, Anthropic-via-adapter, Ollama, vLLM, LM
Studio, OpenRouter, Together. BYO mode = no rate limits.

</td>
<td width="50%" valign="top">

### 🎙️ Voice input
Hold-to-record with live volume meter. Browser-native
`MediaRecorder` (webm/opus on Chromium, mp4 on Safari) →
multipart upload → Whisper / `gpt-4o-mini-transcribe`. Works
in both Mentor and Interviewer chats.

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
</table>

---

## 🏗️ Architecture

```
┌──────────────┐
│  React SPA   │  Vite · shadcn/ui · Tailwind · React Router
└──────┬───────┘
       │ HTTPS + JWT (access + refresh)
       ▼
┌──────────────────────────────────────────────────────────┐
│                 FastAPI Core API                         │
│                                                          │
│  api/   ─ auth, projects, resumes, qa, mentor,           │
│           interviewer, audio                             │
│  domain/ ─ projects (chunker, embedder, summarizer)      │
│           resumes (parser, claim grounder)               │
│           qa (planner, shard generator, merger)          │
│           mentor (LangGraph + ProjectFs tools)           │
│           interviewer (LangGraph + picker + evaluator)   │
│           memory (recall + distiller)                    │
│  infra/ ─ Postgres · Redis · Chroma · BlobStorage        │
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
│ • rate-limit
│ • usage logs
└──────┬──────┘
       │ OpenAI-compatible
       ▼
┌─────────────────────────────────────────────────────────┐
│ OpenAI · Anthropic (adapter) · Ollama · vLLM · OpenRouter │
└─────────────────────────────────────────────────────────┘
```

### Repository layout

```
open-interview/
├── frontend/app/              # Vite + React SPA
├── backend/
│   ├── services/
│   │   ├── core/              # FastAPI app (api / domain / infra)
│   │   ├── gateway/           # GenAI gateway (provider router + rate limiter)
│   │   └── workers/           # arq background jobs
│   └── libs/                  # shared schemas, db models, storage, logging
├── infra/                     # Docker Compose, Dockerfiles
├── config/                    # models.yaml, tiers.yaml, env profiles
├── docs/                      # requirements-and-system-design.md
├── scripts/                   # one-off scripts
└── data/                      # gitignored: blob storage in dev
```

### Tech stack

| Layer | Tools |
| ----- | ----- |
| Frontend | React 18, Vite, TypeScript, Tailwind, shadcn/ui, lucide-react, react-markdown, react-router |
| Core API | FastAPI, SQLAlchemy 2 (async), pydantic v2, LangGraph, httpx, argon2, PyJWT |
| Persistence | Postgres (prod) / SQLite (tests), Redis, Chroma vector DB |
| Workers | arq (Redis-backed task queue) |
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
```

Swap any line for your own provider — Ollama, vLLM, OpenRouter, Together —
as long as it speaks the OpenAI API.

---

## 🧪 Tests

```bash
make test                 # full backend suite (~5s)
.venv/bin/python -m pytest backend/services/core/tests -q
cd frontend/app && npx tsc --noEmit && npx vite build
```

Current coverage:

- Core: 28 tests across security, ingestion (project + resume), QA pipeline,
  mentor streaming, mentor tool-loop, interviewer flow, audio transcription.
- Gateway: 6 tests for catalog routing, BYO vs shared mode, rate limiting,
  usage logging.
- Frontend: typecheck-clean Vite build with code-split markdown vendor chunk.

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
| **Audio** | ✅ | Voice input in chat, server-side Whisper-class transcription |
| **M7** Common KB | 🚧 | Applied-AI question bank + system-design primer seeds |
| **M8** Hardening | 🚧 | Observability, export / wipe, real arq offload of QA generation |

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

Apache 2.0 — see [`LICENSE`](LICENSE) (TBD).

---

<div align="center">
<sub>Made with ☕ and a stubborn belief that interviews should reward the work you actually did.</sub>
</div>
