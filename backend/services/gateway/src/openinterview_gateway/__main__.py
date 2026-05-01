from __future__ import annotations

import os

import uvicorn

from .config import get_settings


def main() -> None:
    s = get_settings()
    reload = os.getenv("OPENINTERVIEW_RELOAD", "0") == "1"
    uvicorn.run(
        "openinterview_gateway.app:app",
        host=s.gateway_host,
        port=s.gateway_port,
        reload=reload,
        reload_dirs=["backend/services/gateway/src", "backend/libs"] if reload else None,
    )


if __name__ == "__main__":
    main()
