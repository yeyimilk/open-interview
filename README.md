# Open Interview

Self-hosted, multi-user interview-preparation platform for software engineers (with first-class support for Applied AI roles).

See `docs/requirements-and-system-design.md` for the full spec.

## Repository layout

- `frontend/` — Vite + React SPA
- `backend/services/core/` — FastAPI core API
- `backend/services/gateway/` — GenAI Model Gateway service
- `backend/services/workers/` — background job workers
- `backend/libs/` — shared backend libraries
- `infra/` — Docker Compose, Dockerfiles
- `config/` — model and tier config, env profiles

## Local dev (recommended) — hot reload everywhere

Stateful services (postgres, redis, chroma) run in Docker; app code runs on your host so file edits trigger instant reloads.

### One-time setup

```bash
make setup                       # creates .venv, installs editable libs+services, npm install
cp config/env.dev.example .env   # local env (uses localhost endpoints)
```

### Daily workflow (one terminal each)

```bash
make infra        # postgres + redis + chroma in Docker (background)
make core         # FastAPI core on http://localhost:8000  (uvicorn --reload)
make gateway      # gateway on http://localhost:9100        (uvicorn --reload)
make workers      # arq worker (auto-restart via watchexec/etc, optional)
make web          # Vite dev server on http://localhost:5173 (HMR)
```

UI: http://localhost:5173
API docs: http://localhost:8000/docs

### Tests

```bash
make test
```

## Full Docker mode (for staging-like runs)

If you don't want host processes:

```bash
docker compose -f infra/docker-compose.local.yml up --build
```

This builds + runs everything in containers; rebuild on every change.

## Status

- M0 — Foundation skeletons + auth + per-tenant isolation
- M1 — GenAI Gateway (BYO + shared key, rate limits, usage logging)
- M2 — Project + resume ingestion (chunk, embed, hierarchical summary, diagrams, claim grounding)
- M3+ — QA generation, Mentor, Interviewer, Memory (in progress)
