from __future__ import annotations

import os

import uvicorn

from .config import get_settings


def main() -> None:
    s = get_settings()
    reload = os.getenv("OPENINTERVIEW_RELOAD", "0") == "1"
    uvicorn.run(
        "openinterview_realtime.app:app",
        host=s.realtime_host,
        port=s.realtime_port,
        reload=reload,
        reload_dirs=(
            ["backend/services/realtime_gateway/src", "backend/libs"]
            if reload
            else None
        ),
    )


if __name__ == "__main__":
    main()
