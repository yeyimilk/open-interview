"""arq worker entrypoint.

Reads REDIS_URL from env so it works inside Docker (redis://redis:6379/0).
Real ingestion / QA / distillation jobs land in M2+/M3 -- M0 ships a `ping`
job and the runtime is ready.
"""
from __future__ import annotations

import os
import asyncio
from urllib.parse import urlparse
from uuid import UUID

from arq.connections import RedisSettings

from openinterview_logging import configure_logging, get_logger

log = get_logger(__name__)


def _redis_settings_from_env() -> RedisSettings:
    url = os.getenv("REDIS_URL")
    if not url:
        try:
            from openinterview_core.config import Settings

            url = Settings().redis_url  # type: ignore[call-arg]
        except Exception:
            url = "redis://localhost:6379/0"
    p = urlparse(url)
    return RedisSettings(
        host=p.hostname or "localhost",
        port=p.port or 6379,
        database=int((p.path or "/0").lstrip("/") or "0"),
        password=p.password,
        ssl=p.scheme == "rediss",
        conn_timeout=int(os.getenv("ARQ_REDIS_CONN_TIMEOUT_SECONDS", "5")),
        conn_retries=int(os.getenv("ARQ_REDIS_CONN_RETRIES", "10")),
        conn_retry_delay=int(os.getenv("ARQ_REDIS_CONN_RETRY_DELAY_SECONDS", "1")),
        retry_on_timeout=True,
    )


async def ping(ctx: dict) -> str:
    log.info("worker_ping")
    return "pong"


async def _kb_service():
    from openinterview_core.config import Settings
    from openinterview_core.infra.blob import build_blob_storage
    from openinterview_core.infra.db import Database
    from openinterview_core.infra.gateway_client import GatewayClient
    from openinterview_core.infra.vector import ChromaVectorStore, InMemoryVectorStore
    from openinterview_core.domain.kb import CommonKBProcessingService

    settings = Settings()  # type: ignore[call-arg]
    db = Database(settings.database_url)
    blob = build_blob_storage(settings)
    gateway = GatewayClient(
        base_url=settings.gateway_url,
        service_token=settings.gateway_service_token,
    )
    vector_store = InMemoryVectorStore()
    try:
        vector_store = ChromaVectorStore(settings.chroma_url)
    except Exception as e:  # noqa: BLE001
        log.warning("worker_vector_store_fallback_inmemory", error=str(e))
    svc = CommonKBProcessingService(
        sessionmaker=db.sessionmaker,
        blob=blob,
        gateway=gateway,
        vector_store=vector_store,
    )
    return db, svc


async def _qa_service():
    from openinterview_core.config import Settings
    from openinterview_core.domain.qa import QAGenerationService
    from openinterview_core.domain.retrieval import InProcessRetrievalService
    from openinterview_core.infra.blob import build_blob_storage
    from openinterview_core.infra.db import Database
    from openinterview_core.infra.gateway_client import GatewayClient
    from openinterview_core.infra.vector import ChromaVectorStore, InMemoryVectorStore

    settings = Settings()  # type: ignore[call-arg]
    db = Database(settings.database_url)
    blob = build_blob_storage(settings)
    gateway = GatewayClient(
        base_url=settings.gateway_url,
        service_token=settings.gateway_service_token,
    )
    vector_store = InMemoryVectorStore()
    try:
        vector_store = ChromaVectorStore(settings.chroma_url)
    except Exception as e:  # noqa: BLE001
        log.warning("worker_vector_store_fallback_inmemory", error=str(e))

    class _RetrievalService:
        async def retrieve(self, request):
            service = InProcessRetrievalService(
                sessionmaker=db.sessionmaker,
                gateway=gateway,
                vector_store=vector_store,
            )
            return await service.retrieve(request)

    svc = QAGenerationService(
        sessionmaker=db.sessionmaker,
        gateway=gateway,
        vector_store=vector_store,
        retrieval_service=_RetrievalService(),
    )
    return db, blob, svc


async def process_common_kb_document(ctx: dict, document_id: str, actor_user_id: str | None = None) -> int:
    db, svc = await _kb_service()
    try:
        ids = await svc.process_document(
            document_id=UUID(document_id),
            actor_user_id=UUID(actor_user_id) if actor_user_id else None,
        )
        return len(ids)
    finally:
        await db.dispose()


async def refresh_common_kb_source(ctx: dict, source_id: str, actor_user_id: str | None = None) -> int:
    db, svc = await _kb_service()
    try:
        ids = await svc.refresh_source(
            source_id=UUID(source_id),
            actor_user_id=UUID(actor_user_id) if actor_user_id else None,
        )
        return len(ids)
    finally:
        await db.dispose()


async def extract_common_kb_items(ctx: dict, document_id: str, actor_user_id: str | None = None) -> int:
    return await process_common_kb_document(ctx, document_id, actor_user_id)


async def embed_common_kb_items(ctx: dict, space_key: str, item_ids: list[str], actor_user_id: str | None = None) -> int:
    db, svc = await _kb_service()
    try:
        await svc.embed_items(
            item_ids=[UUID(x) for x in item_ids],
            actor_user_id=UUID(actor_user_id) if actor_user_id else None,
        )
        return len(item_ids)
    finally:
        await db.dispose()


async def rebuild_company_interview_profiles(ctx: dict, company_key: str | None = None) -> int:
    db, svc = await _kb_service()
    try:
        return await svc.rebuild_company_profiles(company_key=company_key)
    finally:
        await db.dispose()


async def generate_project_qa(
    ctx: dict,
    user_id: str,
    project_id: str,
    position: str,
    level: str,
    _traceparent: str | None = None,
) -> str:
    _log_traceparent(_traceparent)
    db, _blob, svc = await _qa_service()
    try:
        await _retry(
            lambda: svc.run(
                user_id=UUID(user_id),
                project_id=UUID(project_id),
                position=position,
                level=level,
            )
        )
        return "ok"
    finally:
        await db.dispose()


async def generate_resume_qa(
    ctx: dict,
    user_id: str,
    resume_id: str,
    position: str,
    level: str,
    _traceparent: str | None = None,
) -> str:
    _log_traceparent(_traceparent)
    db, _blob, svc = await _qa_service()
    try:
        await _retry(
            lambda: svc.run_for_resume(
                user_id=UUID(user_id),
                resume_id=UUID(resume_id),
                position=position,
                level=level,
            )
        )
        return "ok"
    finally:
        await db.dispose()


class WorkerSettings:
    redis_settings = _redis_settings_from_env()
    max_jobs = int(os.getenv("ARQ_MAX_JOBS", "3"))
    job_timeout = int(os.getenv("ARQ_JOB_TIMEOUT_SECONDS", "900"))
    max_tries = int(os.getenv("ARQ_MAX_TRIES", "3"))
    functions = [
        ping,
        process_common_kb_document,
        refresh_common_kb_source,
        extract_common_kb_items,
        embed_common_kb_items,
        rebuild_company_interview_profiles,
        generate_project_qa,
        generate_resume_qa,
    ]


def main() -> None:
    configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))
    log.info("worker_module_loaded")


async def _retry(call, *, attempts: int | None = None):
    max_attempts = attempts or int(os.getenv("QA_JOB_ATTEMPTS", "3"))
    last: Exception | None = None
    for i in range(max(1, max_attempts)):
        try:
            return await call()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < max_attempts - 1:
                await asyncio.sleep(min(30, 2 ** i))
    raise last or RuntimeError("retry failed")


def _log_traceparent(traceparent: str | None) -> None:
    if traceparent:
        log.info("worker_trace_context_received", traceparent=traceparent)


if __name__ == "__main__":
    main()
