"""Tier-based rate limiter. v1: in-memory per-process. M1+: swap to Redis."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class TierConfig:
    name: str
    rate_limit_rpm: int


class RateLimiter:
    """Sliding-window per (user_id, tier) limiter.

    Skipped entirely for BYO-key requests by callers — this class only sees shared-key calls.
    """

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, rpm: int) -> bool:
        if rpm <= 0:
            return True
        now = time.monotonic()
        window = 60.0
        with self._lock:
            q = self._events[key]
            cutoff = now - window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= rpm:
                return False
            q.append(now)
            return True
