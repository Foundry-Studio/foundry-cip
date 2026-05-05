# foundry: kind=test domain=client-intelligence-platform
"""Tests for ``cip.integration_mesh.rate_limit.TokenBucket``.

Three scenarios per plan §4.3 acceptance criteria:
  - burst capacity (immediate consumption up to ``burst``)
  - rate-limited pause (overburst blocks for the right duration)
  - thread-safety (concurrent acquires serialize correctly)
"""
from __future__ import annotations

import threading
import time

from cip.integration_mesh.base import RateLimitPolicy
from cip.integration_mesh.rate_limit import TokenBucket


class TestBurstCapacity:
    def test_initial_burst_consumes_immediately(self) -> None:
        # 1 rps, burst=5 → 5 immediate consumes should take ~zero wall time.
        bucket = TokenBucket(RateLimitPolicy(requests_per_second=1.0, burst=5))
        start = time.monotonic()
        for _ in range(5):
            bucket.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"5 burst consumes took {elapsed:.3f}s; expected ~0"

    def test_overburst_blocks_at_rate(self) -> None:
        # 10 rps, burst=2 → 3rd consume waits ~0.1s (1 / 10).
        bucket = TokenBucket(RateLimitPolicy(requests_per_second=10.0, burst=2))
        bucket.acquire()
        bucket.acquire()
        start = time.monotonic()
        bucket.acquire()
        elapsed = time.monotonic() - start
        # Allow generous slack for CI clock variance, but bound from below.
        assert 0.05 < elapsed < 0.5, (
            f"3rd consume elapsed {elapsed:.3f}s; expected ~0.1s"
        )


class TestSteadyState:
    def test_paces_at_rate(self) -> None:
        # 20 rps, burst=1; 4 consumes = burst + 3 timed @ 0.05s each ≈ 0.15s.
        bucket = TokenBucket(RateLimitPolicy(requests_per_second=20.0, burst=1))
        bucket.acquire()  # consume initial burst
        start = time.monotonic()
        for _ in range(3):
            bucket.acquire()
        elapsed = time.monotonic() - start
        assert 0.10 < elapsed < 0.50, (
            f"3 paced consumes elapsed {elapsed:.3f}s; expected ~0.15s"
        )


class TestThreadSafety:
    def test_concurrent_acquires_serialize(self) -> None:
        # 10 rps, burst=1. Drain initial token; 5 threads each acquire once →
        # ≥0.4s minimum (5 × 0.1s budget).
        bucket = TokenBucket(RateLimitPolicy(requests_per_second=10.0, burst=1))
        bucket.acquire()  # drain burst

        results: list[float] = []
        results_lock = threading.Lock()

        def worker() -> None:
            t0 = time.monotonic()
            bucket.acquire()
            with results_lock:
                results.append(time.monotonic() - t0)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.35, (
            f"5 concurrent acquires elapsed {elapsed:.3f}s; expected >= 0.4s"
        )
        assert len(results) == 5
