"""Realtime gateway FastAPI app.

Self-contained service so this folder can be split out as its own
micro-service later. It depends on `core` only via HTTP.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from openinterview_logging import configure_logging, get_logger

from .api import health as health_api
from .api import ws as ws_api
from .clients.core_client import CoreClient
from .clients.gateway_client import GatewayClient
from .config import Settings, get_settings

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    s: Settings = app.state.settings
    app.state.gateway_client = GatewayClient(
        base_url=s.gateway_url,
        service_token=s.gateway_service_token,
    )
    app.state.core_client = CoreClient(
        base_url=s.core_url,
        service_token=s.realtime_internal_token,
    )
    log.info("realtime_startup", port=s.realtime_port)
    try:
        yield
    finally:
        log.info("realtime_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    configure_logging(level=s.log_level, json_output=s.log_json)
    app = FastAPI(
        title="Open Interview — Realtime Gateway",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.state.settings = s
    app.include_router(health_api.router)
    app.include_router(ws_api.router)
    return app


app = create_app()
