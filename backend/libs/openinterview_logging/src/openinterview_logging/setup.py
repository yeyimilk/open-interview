"""Structured logging setup. Call configure_logging() once at startup."""
from __future__ import annotations

import asyncio
import logging
import sys

import structlog


class _DropAsyncpgTerminateCancelled(logging.Filter):
    """Silences SQLAlchemy's noisy "Exception terminating connection" log
    when the underlying cause is just an `asyncio.CancelledError` raised
    because the HTTP client disconnected mid-request.

    This happens routinely in our setup because:
      * the realtime gateway streams SSE responses from core and may abort
        them when a barge-in arrives, and
      * the browser polls for messages and cancels prior fetches when the
        UI re-renders.

    The connection is reaped correctly either way; only the log line is
    misleading. We deliberately keep all *other* connection-termination
    errors visible.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.getMessage().startswith("Exception terminating connection"):
            return True
        exc_info = record.exc_info
        if not exc_info:
            return True
        exc = exc_info[1]
        if isinstance(exc, asyncio.CancelledError):
            return False
        # `anyio.get_cancelled_exc_class()` may return a subclass on some
        # backends; match by name to stay implementation-agnostic.
        if exc is not None and "CancelledError" in type(exc).__name__:
            return False
        return True


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    # Quiet the request-cancelled DB-terminate noise everywhere SQLAlchemy
    # may log it from. The filter is a no-op for unrelated messages.
    _flt = _DropAsyncpgTerminateCancelled()
    for name in ("sqlalchemy.pool", "sqlalchemy.pool.impl", "sqlalchemy"):
        logging.getLogger(name).addFilter(_flt)
    # Root too — SQLAlchemy sometimes attaches a per-pool logger whose name
    # we can't predict (e.g. `sqlalchemy.pool.impl.AsyncAdaptedQueuePool.0x..`).
    logging.getLogger().addFilter(_flt)
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
