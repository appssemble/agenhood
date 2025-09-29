from __future__ import annotations

import time


class FixedWindowLimiter:
    """Simple per-key fixed-window rate limiter.  In-process; good enough for
    v1 single-host (spec §10).  Replaceable by a shared store later."""

    def __init__(self, max_attempts: int = 10, window_seconds: int = 300) -> None:
        self.max = max_attempts
        self.window = window_seconds
        # key -> (window_start, count)
        self._buckets: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        t: float = time.monotonic() if now is None else now
        start, count = self._buckets.get(key, (t, 0))
        if t - start >= self.window:
            start, count = t, 0
        if count >= self.max:
            self._buckets[key] = (start, count)
            return False
        self._buckets[key] = (start, count + 1)
        return True


# Module-level singleton used by the login endpoint.
login_limiter = FixedWindowLimiter(max_attempts=10, window_seconds=300)
