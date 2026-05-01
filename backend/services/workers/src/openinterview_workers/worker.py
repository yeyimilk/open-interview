"""arq worker entrypoint.

Reads REDIS_URL from env so it works inside Docker (redis://redis:6379/0).
Real ingestion / QA / distillation jobs land in M2+/M3 -- M0 ships a `ping`
job and the runtime is ready.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from arq.connections import RedisSettings

from openinterview_logging import configure_logging, get_logger

log = get_logger(__name__)


def _redis_settings_from_env() -> RedisSettings:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    p = urlparse(url)
    return RedisSettings(
        host=p.hostname or "localhost",
        port=p.port or 6379,
        database=int((p.path or "/0").lstrip("/") or "0"),
        password=p.password,
        ssl=p.scheme == "rediss",
    )


async def ping(ctx: dict) -> str:
    log.info("worker_ping")
    return "pong"


class WorkerSettings:
    redis_settings = _redis_settings_from_env()
    functions = [ping]


def main() -> None:
    configure_logging(level=os.getenv("LOG_LEVEL", "INFO"))
    log.info("worker_module_loaded")


if __name__ == "__main__":
    main()
