from __future__ import annotations

from urllib.parse import urlparse

from arq import create_pool
from arq.connections import RedisSettings

from .tracing import current_trace_headers


def redis_settings_from_url(url: str) -> RedisSettings:
    p = urlparse(url)
    return RedisSettings(
        host=p.hostname or "localhost",
        port=p.port or 6379,
        database=int((p.path or "/0").lstrip("/") or "0"),
        password=p.password,
        ssl=p.scheme == "rediss",
    )


async def enqueue_arq_job(redis_url: str, job_name: str, *args, **kwargs) -> bool:
    try:
        trace_headers = current_trace_headers()
        if "traceparent" in trace_headers and "_traceparent" not in kwargs:
            kwargs["_traceparent"] = trace_headers["traceparent"]
        redis = await create_pool(redis_settings_from_url(redis_url))
        try:
            await redis.enqueue_job(job_name, *args, **kwargs)
        finally:
            await redis.close()
        return True
    except Exception:
        return False
