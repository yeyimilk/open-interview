from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "realtime"}
