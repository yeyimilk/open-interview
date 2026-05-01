core: OPENINTERVIEW_RELOAD=1 .venv/bin/python -m openinterview_core
gateway: OPENINTERVIEW_RELOAD=1 MODELS_YAML_PATH=./config/models.yaml TIERS_YAML_PATH=./config/tiers.yaml .venv/bin/python -m openinterview_gateway
workers: .venv/bin/python -m arq openinterview_workers.worker.WorkerSettings
web: cd frontend/app && npm run dev
wabridge: cd backend/services/whatsapp_bridge && npm run dev
