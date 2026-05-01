"""Tiny SSE helper -- formats events as `event: <name>\\ndata: <json>\\n\\n`."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any


def sse_format(event: str, data: Any) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


async def sse_stream_from(events: AsyncIterator[dict]) -> AsyncIterator[bytes]:
    async for ev in events:
        kind = ev.get("type", "message")
        yield sse_format(kind, ev)
