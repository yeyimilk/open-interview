from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from ..domain.gateway_service import GatewayService


def require_service_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    expected: str = request.app.state.settings.gateway_service_token
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing token")
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid service token")


def get_service(request: Request) -> GatewayService:
    svc = getattr(request.app.state, "service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="gateway not configured")
    return svc


__all__ = ["require_service_token", "get_service"]
