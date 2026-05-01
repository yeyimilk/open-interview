# Local dev workflow.
# Stateful services run in Docker; everything else runs on the host with hot reload.
#
# First-time setup:
#   make setup
#
# Day-to-day (run each in its own terminal):
#   make infra       # postgres + redis + chroma in Docker (background)
#   make core        # FastAPI core API on http://localhost:8000  (auto-reload)
#   make gateway     # GenAI gateway on http://localhost:9100      (auto-reload)
#   make workers     # arq worker
#   make web         # Vite dev server on http://localhost:5173    (HMR)
#
# Convenience:
#   make all         # infra + core + gateway + workers + web in one tab via overmind/foreman if installed,
#                    # otherwise prints the 5-tab instructions.

PY := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest

.DEFAULT_GOAL := help

.PHONY: help setup frontend-install \
        infra infra-down infra-reset infra-logs \
        _kill-host down down-all \
        core gateway workers web all \
        test fmt

help:
	@echo "Targets:"
	@echo "  setup        - create venv, install backend libs+services in editable mode, frontend deps"
	@echo "  infra        - start postgres/redis/chroma in Docker (background)"
	@echo "  infra-down   - stop infra (keeps data)"
	@echo "  infra-reset  - stop infra AND wipe volumes (postgres + chroma data)"
	@echo "  infra-logs   - tail infra logs"
	@echo "  down         - stop everything: host dev procs (core/gateway/workers/web) + infra"
	@echo "  down-all     - same as down, plus wipe infra volumes"
	@echo "  core         - run core FastAPI service with hot reload"
	@echo "  gateway      - run gateway service with hot reload"
	@echo "  workers      - run arq worker"
	@echo "  web          - run Vite dev server"
	@echo "  all          - run infra + core + gateway + workers + web in one terminal"
	@echo "                 (uses overmind / hivemind / honcho — auto-detected)"
	@echo "  test         - run all backend tests"
	@echo "  fmt          - (placeholder) ruff format"
	@echo ""

# ---------- setup ----------

setup: .venv frontend-install
	@echo "Setup complete. Copy config/env.dev.example to .env if you haven't yet:"
	@echo "  cp config/env.dev.example .env"

.venv:
	python3 -m venv .venv
	$(PIP) install --upgrade pip wheel setuptools
	$(PIP) install -e backend/libs/openinterview_schemas \
	               -e backend/libs/openinterview_logging \
	               -e backend/libs/openinterview_storage \
	               -e backend/libs/openinterview_db
	$(PIP) install -e "backend/services/core[test]" \
	               -e backend/services/gateway \
	               -e backend/services/workers
	$(PIP) install aiosqlite

frontend-install:
	cd frontend/app && npm install

# ---------- infra ----------

infra:
	docker compose -f infra/docker-compose.dev.yml up -d

infra-down:
	docker compose -f infra/docker-compose.dev.yml down

infra-reset:
	docker compose -f infra/docker-compose.dev.yml down -v

infra-logs:
	docker compose -f infra/docker-compose.dev.yml logs -f

# Stop host dev processes started via `make core/gateway/workers/web`.
# Matches the exact module/script invocations to avoid killing unrelated procs.
_kill-host:
	-@pkill -f "overmind start -f Procfile" 2>/dev/null || true
	-@pkill -f "hivemind Procfile" 2>/dev/null || true
	-@pkill -f "honcho start -f Procfile" 2>/dev/null || true
	-@pkill -f "python -m openinterview_core" 2>/dev/null || true
	-@pkill -f "python -m openinterview_gateway" 2>/dev/null || true
	-@pkill -f "arq openinterview_workers.worker.WorkerSettings" 2>/dev/null || true
	-@pkill -f "vite" 2>/dev/null || true
	@echo "Host dev processes stopped (if any were running)."

down: _kill-host infra-down
	@echo "Stack down. Data volumes preserved. Use 'make down-all' to also wipe data."

down-all: _kill-host infra-reset
	@echo "Stack down and volumes wiped."

# ---------- run apps (host, hot reload) ----------

# Each target picks up .env (config/env.dev.example -> .env).

core:
	@if [ ! -f .env ]; then echo "ERROR: .env missing. Run: cp config/env.dev.example .env"; exit 1; fi
	OPENINTERVIEW_RELOAD=1 $(PY) -m openinterview_core

gateway:
	@if [ ! -f .env ]; then echo "ERROR: .env missing. Run: cp config/env.dev.example .env"; exit 1; fi
	OPENINTERVIEW_RELOAD=1 \
	MODELS_YAML_PATH=$(PWD)/config/models.yaml \
	TIERS_YAML_PATH=$(PWD)/config/tiers.yaml \
	$(PY) -m openinterview_gateway

workers:
	@if [ ! -f .env ]; then echo "ERROR: .env missing. Run: cp config/env.dev.example .env"; exit 1; fi
	$(PY) -m arq openinterview_workers.worker.WorkerSettings

web:
	cd frontend/app && npm run dev

# ---------- run everything in one terminal ----------

# Starts infra (Docker) and then a process manager that runs core/gateway/workers/web together.
# Order of preference: overmind (best, supports per-proc tmux), hivemind, honcho (pip).
all: infra wait-infra
	@if [ ! -f .env ]; then echo "ERROR: .env missing. Run: cp config/env.dev.example .env"; exit 1; fi
	@$(PY) -c "import arq, openinterview_core, openinterview_gateway, openinterview_workers" 2>/dev/null || \
		( echo "Some Python services not installed in venv. Running 'make setup'..."; $(MAKE) setup )
	@if [ ! -x frontend/app/node_modules/.bin/vite ]; then \
		echo "Installing frontend dependencies..."; \
		cd frontend/app && npm install; \
	fi

# Wait for postgres + redis containers to report healthy before starting host procs.
.PHONY: wait-infra
wait-infra:
	@printf "Waiting for postgres..."
	@for i in $$(seq 1 30); do \
		if docker compose -f infra/docker-compose.dev.yml exec -T postgres pg_isready -U openinterview -d openinterview >/dev/null 2>&1; then \
			echo " ready."; break; \
		fi; \
		printf "."; sleep 1; \
		if [ $$i -eq 30 ]; then echo " TIMEOUT"; exit 1; fi; \
	done
	@printf "Waiting for redis..."
	@for i in $$(seq 1 30); do \
		if docker compose -f infra/docker-compose.dev.yml exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then \
			echo " ready."; break; \
		fi; \
		printf "."; sleep 1; \
		if [ $$i -eq 30 ]; then echo " TIMEOUT"; exit 1; fi; \
	done
	@if command -v overmind >/dev/null 2>&1; then \
		echo "Using overmind. Tip: 'overmind connect <proc>' in another terminal to attach."; \
		overmind start -f Procfile; \
	elif command -v hivemind >/dev/null 2>&1; then \
		echo "Using hivemind."; \
		hivemind Procfile; \
	elif [ -x .venv/bin/honcho ]; then \
		echo "Using honcho (.venv)."; \
		.venv/bin/honcho start -f Procfile; \
	elif command -v honcho >/dev/null 2>&1; then \
		echo "Using honcho."; \
		honcho start -f Procfile; \
	else \
		echo ""; \
		echo "No process manager found. Install one of:"; \
		echo "  brew install overmind          # recommended (macOS)"; \
		echo "  brew install hivemind"; \
		echo "  $(PIP) install honcho          # pure-Python, no brew needed"; \
		echo ""; \
		echo "Or run each in its own terminal: make core / gateway / workers / web"; \
		exit 1; \
	fi

# ---------- tests ----------

test:
	$(PYTEST) backend -q
