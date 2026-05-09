from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, Any]:
    return await _health_payload(request)


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    payload = await _health_payload(request)
    status = 200 if payload["status"] == "ok" else 503
    return JSONResponse(payload, status_code=status)


async def _health_payload(request: Request) -> dict[str, Any]:
    checks: dict[str, Any] = {"core": {"status": "ok"}}

    db = getattr(request.app.state, "db", None)
    if db is None:
        checks["database"] = {"status": "unavailable", "detail": "not configured"}
    else:
        try:
            async with db.session() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = {"status": "ok"}
        except Exception as e:  # pragma: no cover
            checks["database"] = {"status": "unavailable", "detail": str(e)}

    checks["whatsapp_bridge"] = await _whatsapp_bridge_check(request)
    required = ("core", "database")
    status = "ok" if all(checks[name]["status"] == "ok" for name in required) else "degraded"
    if checks["whatsapp_bridge"]["status"] == "unavailable":
        status = "degraded"
    return {"status": status, "checks": checks}


async def _whatsapp_bridge_check(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "messenger_registry", None)
    if registry is None:
        return {"status": "not_configured"}
    item = registry.get("whatsapp")
    if item is None:
        return {"status": "not_configured"}
    plugin = item[1]
    health = getattr(plugin, "health", None)
    if health is None:
        return {"status": "unknown"}
    try:
        result = await health()
        if isinstance(result, dict):
            return {"status": "ok", **result}
        return {"status": "ok"}
    except Exception as e:
        return {"status": "unavailable", "detail": str(e)}
