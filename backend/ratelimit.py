"""Small in-process sliding-window rate limiter.

Each worker process keeps its own counters, so with N workers the effective limit is up to N times
higher. That is fine for its job here (stopping one client hammering the public endpoint); nginx
`limit_req` should be the first line of defence in production.
"""
import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 50_000):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self.max_keys:
                    self._prune(cutoff)
                hits = self._hits[key] = deque()
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def _prune(self, cutoff: float) -> None:
        for k in [k for k, h in self._hits.items() if not h or h[-1] <= cutoff]:
            del self._hits[k]
        if len(self._hits) >= self.max_keys:  # still full of active keys: start over rather than grow
            self._hits.clear()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
