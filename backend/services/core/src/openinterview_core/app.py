"""FastAPI app factory. Wires config, db, security, blob storage, routers."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from openinterview_db import Base
from openinterview_logging import configure_logging, get_logger

from .api.v1 import api_keys as api_keys_v1
from .api.v1 import admin_kb as admin_kb_v1
from .api.v1 import admin_users as admin_users_v1
from .api.v1 import model_preferences as model_preferences_v1
from .api.v1 import audio as audio_v1
from .api.v1 import auth as auth_v1
from .api.v1 import general as general_v1
from .api.v1 import health as health_v1
from .api.v1 import interviewer as interviewer_v1
from .api.v1 import kb as kb_v1
from .api.v1 import me as me_v1
from .api.v1 import mentor as mentor_v1
from .api.v1 import messaging as messaging_v1
from .api.v1 import projects as projects_v1
from .api.v1 import qa as qa_v1
from .api.v1 import realtime as realtime_v1
from .api.v1 import resumes as resumes_v1
from .config import Settings, get_settings
from .infra.blob import build_blob_storage
from .infra.db import Database
from .security import SecretBox, TokenIssuer

log = get_logger(__name__)


async def _dev_patch_columns(conn) -> None:
    """Idempotent dev-only schema patches for new columns.

    `Base.metadata.create_all` only creates missing *tables*; it never
    ALTERs an existing one. For local dev we don't have Alembic wired in,
    so we apply a couple of small patches here. Each guards itself by
    introspecting `information_schema` (Postgres) / `PRAGMA` (SQLite).
    """
    from sqlalchemy import text

    dialect = conn.dialect.name

    async def _has_column(table: str, column: str) -> bool:
        if dialect == "postgresql":
            r = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            )
            return r.first() is not None
        if dialect == "sqlite":
            r = await conn.execute(text(f"PRAGMA table_info({table})"))
            return any(row[1] == column for row in r.fetchall())
        return True  # unknown dialect — let it fail loudly downstream

    async def _has_constraint(table: str, constraint: str) -> bool:
        if dialect == "postgresql":
            r = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.table_constraints "
                    "WHERE table_name = :t AND constraint_name = :c"
                ),
                {"t": table, "c": constraint},
            )
            return r.first() is not None
        return True

    if not await _has_column("messenger_links", "filter_mode"):
        await conn.execute(
            text(
                "ALTER TABLE messenger_links "
                "ADD COLUMN filter_mode VARCHAR(16) "
                "NOT NULL DEFAULT 'dms_only'"
            )
        )
    if not await _has_column("messenger_active_sessions", "conversation_id"):
        await conn.execute(
            text(
                "ALTER TABLE messenger_active_sessions "
                "ADD COLUMN conversation_id VARCHAR(256) NULL"
            )
        )
    if dialect == "postgresql":
        old_constraint = "uq_messenger_active_user_channel"
        new_constraint = "uq_messenger_active_user_channel_conversation"
        if await _has_constraint("messenger_active_sessions", old_constraint):
            await conn.execute(
                text(
                    "ALTER TABLE messenger_active_sessions "
                    f"DROP CONSTRAINT {old_constraint}"
                )
            )
        if not await _has_constraint("messenger_active_sessions", new_constraint):
            await conn.execute(
                text(
                    "ALTER TABLE messenger_active_sessions "
                    f"ADD CONSTRAINT {new_constraint} "
                    "UNIQUE (user_id, channel, conversation_id)"
                )
            )

    # qa_sets: resume scoping. Older DBs have a NOT NULL project_id and no
    # resume_id / scope columns. We add the new columns and relax the NOT NULL
    # on project_id so a row can be project- *or* resume-scoped.
    if not await _has_column("qa_sets", "resume_id"):
        await conn.execute(
            text(
                "ALTER TABLE qa_sets "
                "ADD COLUMN resume_id UUID NULL"
            )
        )
    if not await _has_column("qa_sets", "scope"):
        await conn.execute(
            text(
                "ALTER TABLE qa_sets "
                "ADD COLUMN scope VARCHAR(16) NOT NULL DEFAULT 'project'"
            )
        )
    # Relaxing NOT NULL is a Postgres-only operation; SQLite re-creates tables
    # for us via create_all so this branch is a no-op there.
    if dialect == "postgresql":
        await conn.execute(
            text("ALTER TABLE qa_sets ALTER COLUMN project_id DROP NOT NULL")
        )

    # qa_items.meta: optional resume-claim context for individual questions.
    if not await _has_column("qa_items", "meta"):
        await conn.execute(
            text("ALTER TABLE qa_items ADD COLUMN meta JSON NULL")
        )

    # interview_evaluations: delivery rubric (audio-mode interviews).
    if not await _has_column("interview_evaluations", "delivery_score"):
        await conn.execute(
            text(
                "ALTER TABLE interview_evaluations "
                "ADD COLUMN delivery_score FLOAT NULL"
            )
        )
    if not await _has_column("interview_evaluations", "delivery_summary"):
        await conn.execute(
            text(
                "ALTER TABLE interview_evaluations "
                "ADD COLUMN delivery_summary JSON NULL"
            )
        )


async def _promote_bootstrap_admin(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    email = (settings.openinterview_bootstrap_admin_email or "").strip().lower()
    if not email:
        return

    from .infra.db.user_repository import SqlUserRepository

    async with app.state.db.session() as session:
        repo = SqlUserRepository(session)
        user = await repo.get_by_email(email)
        if user is None or user.is_admin:
            return
        await repo.update_user(user.id, is_admin=True)
        log.info("bootstrap_admin_promoted", email=email)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    db: Database = app.state.db
    # Auto-create tables in dev. Production should rely on Alembic migrations.
    if settings.openinterview_env == "local":
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Lightweight column patch-ups for dev. `create_all` only adds
            # missing tables; it does NOT add new columns to existing ones.
            await _dev_patch_columns(conn)
    await _promote_bootstrap_admin(app)

    # Messenger runtime: kernel + plugin registry. Plugins discovered from
    # `domain/messengers/plugins/<id>/plugin.json`.
    try:
        from .domain.messengers.wiring import build_messenger_runtime

        kernel, registry = build_messenger_runtime(app)
        app.state.messenger_kernel = kernel
        app.state.messenger_registry = registry
        for manifest, plugin in registry.all():
            try:
                router = plugin.webhook_router()
                app.include_router(router, prefix=f"/webhooks/{manifest.id}")
            except Exception as e:  # pragma: no cover - logged
                log.error(
                    "messenger_router_mount_failed",
                    id=manifest.id, error=str(e),
                )
    except Exception as e:  # pragma: no cover - logged
        log.error("messenger_wiring_failed", error=str(e))
        app.state.messenger_kernel = None
        app.state.messenger_registry = None

    log.info("core_startup", env=settings.openinterview_env)
    try:
        yield
    finally:
        if getattr(app.state, "messenger_registry", None) is not None:
            for _, plugin in app.state.messenger_registry.all():
                try:
                    await plugin.shutdown()
                except Exception:
                    pass
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
    app.include_router(model_preferences_v1.router, prefix=api_prefix)
    app.include_router(model_preferences_v1.providers_router, prefix=api_prefix)
    app.include_router(projects_v1.router, prefix=api_prefix)
    app.include_router(resumes_v1.router, prefix=api_prefix)
    app.include_router(qa_v1.router, prefix=api_prefix)
    app.include_router(kb_v1.router, prefix=api_prefix)
    app.include_router(admin_kb_v1.router, prefix=api_prefix)
    app.include_router(admin_users_v1.router, prefix=api_prefix)
    app.include_router(mentor_v1.router, prefix=api_prefix)
    app.include_router(general_v1.router, prefix=api_prefix)
    app.include_router(interviewer_v1.router, prefix=api_prefix)
    app.include_router(audio_v1.router, prefix=api_prefix)
    app.include_router(messaging_v1.router, prefix=api_prefix)
    app.include_router(realtime_v1.router, prefix=api_prefix)

    # Singleton GatewayClient (used by domain services). Per-user model
    # preferences are looked up automatically via ``override_resolver`` so
    # that callers can keep using logical model names; if the user has
    # picked a different (provider, endpoint, model_id) it transparently
    # overrides the catalog.
    from .infra.gateway_client import GatewayClient
    from .infra.db.user_model_preference_repository import (
        SqlUserModelPreferenceRepository,
    )
    from openinterview_schemas import ProviderOverride

    sm = app.state.db.sessionmaker

    async def _override_resolver(
        user_id, role: str
    ) -> ProviderOverride | None:
        async with sm() as s:
            row = await SqlUserModelPreferenceRepository(s).get(
                user_id=user_id, role=role
            )
        if row is None:
            return None
        return ProviderOverride(
            provider=row.provider,
            endpoint=row.endpoint,
            model_id=row.model_id,
        )

    app.state.gateway = GatewayClient(
        base_url=s.gateway_url,
        service_token=s.gateway_service_token,
        override_resolver=_override_resolver,
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
