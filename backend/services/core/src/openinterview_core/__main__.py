from __future__ import annotations

import os

import uvicorn

from .config import get_settings


def main() -> None:
    s = get_settings()
    reload = os.getenv("OPENINTERVIEW_RELOAD", "0") == "1"
    uvicorn.run(
        "openinterview_core.app:app",
        host=s.core_host,
        port=s.core_port,
        reload=reload,
        reload_dirs=["backend/services/core/src", "backend/libs"] if reload else None,
    )


if __name__ == "__main__":
    main()
