# foundry: kind=service domain=client-intelligence-platform touches=integration
"""In-process token bucket for ``RateLimitPolicy`` (M2 §4.3 binding).

Used by the orchestrator to pace ``stream_records()`` calls. Not distributed —
for cross-process rate limiting in Phase 2+, swap for a Redis-backed
implementation; the public API (``acquire()``) stays identical.

v2 fix (QC L-26 / Senior #3): the lock is released around ``time.sleep`` so
shared buckets across threads don't serialize. Token math is re-checked on
each loop iteration after sleep.
"""
from __future__ import annotations

import threading
import time

from .base import RateLimitPolicy


class TokenBucket:
    """Thread-safe token bucket for in-process rate limiting."""

    def __init__(self, policy: RateLimitPolicy) -> None:
        self.policy = policy
        self._tokens: float = float(policy.burst)
        self._last: float = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until ``tokens`` tokens are available; consume and return.

        v2 fix: lock is released around ``time.sleep`` so shared buckets
        across threads don't serialize on the sleep path.
        """
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(
                    float(self.policy.burst),
                    self._tokens + elapsed * self.policy.requests_per_second,
                )
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                shortfall = tokens - self._tokens
                sleep_for = shortfall / self.policy.requests_per_second
            # Lock released — other threads can make progress while we sleep.
            time.sleep(sleep_for)
