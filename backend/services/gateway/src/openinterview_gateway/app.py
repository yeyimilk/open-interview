"""Gateway FastAPI app factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from openinterview_db import Base, make_engine, make_sessionmaker
from openinterview_logging import configure_logging, get_logger

from .api.v1 import audio as audio_v1
from .api.v1 import chat as chat_v1
from .api.v1 import embeddings as embed_v1
from .api.v1 import health as health_v1
from .api.v1 import providers as providers_v1
from .api.v1 import realtime as realtime_v1
from .config import Settings, get_settings
from .domain.rate_limit.tiers import TierCatalog
from .domain.routing.catalog import ModelCatalog
from .wiring import build_service

log = get_logger(__name__)


def _make_decrypter(master_key: str):
    # Defer import to keep gateway loosely coupled; SecretBox lives in core.
    # We re-implement here to avoid a circular package dependency.
    import hashlib

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    derived = hashlib.sha256(master_key.encode("utf-8")).digest()

    def _decrypt(blob: bytes) -> str:
        if len(blob) < 13:
            raise ValueError("ciphertext too short")
        nonce, ct = blob[:12], blob[12:]
        return AESGCM(derived).decrypt(nonce, ct, None).decode("utf-8")

    return _decrypt


@asynccontextmanager
async def _lifespan(app: FastAPI):
    s: Settings = app.state.settings

    # Catalog + tiers
    try:
        app.state.catalog = ModelCatalog.from_yaml(s.models_yaml_path)
    except FileNotFoundError:
        app.state.catalog = None
        log.warning("gateway_catalog_missing", path=s.models_yaml_path)
    try:
        app.state.tier_catalog = TierCatalog.from_yaml(s.tiers_yaml_path)
    except FileNotFoundError:
        app.state.tier_catalog = TierCatalog({}, default="free")
        log.warning("gateway_tiers_missing", path=s.tiers_yaml_path)

    # DB
    engine = make_engine(s.database_url)
    sm = make_sessionmaker(engine)
    app.state.engine = engine
    app.state.sessionmaker = sm
    if s.database_url.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Service
    if app.state.catalog is not None:
        app.state.service = build_service(
            settings=s,
            catalog=app.state.catalog,
            tiers=app.state.tier_catalog,
            sessionmaker=sm,
            decrypt_fn=_make_decrypter(s.openinterview_master_key),
            provider=getattr(app.state, "provider_override", None),
        )
    else:
        app.state.service = None

    log.info("gateway_startup")
    try:
        yield
    finally:
        await engine.dispose()
        log.info("gateway_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    configure_logging(level=s.log_level, json_output=s.log_json)

    app = FastAPI(title="Open Interview — GenAI Gateway", version="0.1.0", lifespan=_lifespan)
    app.state.settings = s

    app.include_router(health_v1.router, prefix="/v1")
    app.include_router(chat_v1.router, prefix="/v1")
    app.include_router(embed_v1.router, prefix="/v1")
    app.include_router(audio_v1.router, prefix="/v1")
    app.include_router(providers_v1.router, prefix="/v1")
    app.include_router(realtime_v1.router, prefix="/v1")

    return app


app = create_app()
