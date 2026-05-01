"""FastAPI app factory. Wires config, db, security, blob storage, routers."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from openinterview_db import Base
from openinterview_logging import configure_logging, get_logger

from .api.v1 import api_keys as api_keys_v1
from .api.v1 import audio as audio_v1
from .api.v1 import auth as auth_v1
from .api.v1 import health as health_v1
from .api.v1 import interviewer as interviewer_v1
from .api.v1 import me as me_v1
from .api.v1 import mentor as mentor_v1
from .api.v1 import projects as projects_v1
from .api.v1 import qa as qa_v1
from .api.v1 import resumes as resumes_v1
from .config import Settings, get_settings
from .infra.blob import build_blob_storage
from .infra.db import Database
from .security import SecretBox, TokenIssuer

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    db: Database = app.state.db
    # Auto-create tables in dev. Production should rely on Alembic migrations.
    if settings.openinterview_env == "local":
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    log.info("core_startup", env=settings.openinterview_env)
    try:
        yield
    finally:
        await db.dispose()
        log.info("core_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    configure_logging(level=s.log_level, json_output=s.log_json)

    app = FastAPI(title="Open Interview — Core API", version="0.1.0", lifespan=_lifespan)
    app.state.settings = s
    app.state.db = Database(s.database_url)
    app.state.token_issuer = TokenIssuer(
        secret=s.jwt_secret,
        access_ttl_s=s.jwt_access_ttl_s,
        refresh_ttl_s=s.jwt_refresh_ttl_s,
    )
    app.state.secret_box = SecretBox(s.openinterview_master_key)
    app.state.blob = build_blob_storage(s)

    api_prefix = "/api/v1"
    app.include_router(health_v1.router, prefix=api_prefix)
    app.include_router(auth_v1.router, prefix=api_prefix)
    app.include_router(me_v1.router, prefix=api_prefix)
    app.include_router(api_keys_v1.router, prefix=api_prefix)
    app.include_router(projects_v1.router, prefix=api_prefix)
    app.include_router(resumes_v1.router, prefix=api_prefix)
    app.include_router(qa_v1.router, prefix=api_prefix)
    app.include_router(mentor_v1.router, prefix=api_prefix)
    app.include_router(interviewer_v1.router, prefix=api_prefix)
    app.include_router(audio_v1.router, prefix=api_prefix)

    # Singleton GatewayClient (used by domain services)
    from .infra.gateway_client import GatewayClient

    app.state.gateway = GatewayClient(
        base_url=s.gateway_url, service_token=s.gateway_service_token
    )

    # Vector store: Chroma when CHROMA_URL is reachable; in-memory otherwise.
    from .infra.vector import InMemoryVectorStore

    app.state.vector_store = InMemoryVectorStore()
    try:
        from .infra.vector import ChromaVectorStore

        app.state.vector_store = ChromaVectorStore(s.chroma_url)
        log.info("vector_store_chroma", url=s.chroma_url)
    except Exception as e:
        log.warning("vector_store_fallback_inmemory", error=str(e))

    return app


app = create_app()
