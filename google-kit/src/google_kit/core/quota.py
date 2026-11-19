"""Per-op quota counters and token-bucket rate limiter for google-kit core (R23).

- PerOpCounter: thread-safe per-operation call counter.
- TokenBucket:  simple token-bucket rate limiter.
- QuotaGuard:   wraps a callable with per-op counting + bucket gating;
                raises QuotaRateLimit on bucket exhaustion.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, TypeVar

from google_kit.core.errors import QuotaRateLimit

T = TypeVar("T")


class PerOpCounter:
    """Thread-safe per-operation call counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def increment(self, op: str) -> int:
        """Increment the counter for op and return the new count."""
        with self._lock:
            self._counts[op] = self._counts.get(op, 0) + 1
            return self._counts[op]

    def get(self, op: str) -> int:
        """Return the current count for op (0 if never incremented)."""
        with self._lock:
            return self._counts.get(op, 0)

    def snapshot(self) -> dict[str, int]:
        """Return a copy of all current counts."""
        with self._lock:
            return dict(self._counts)

    def reset(self) -> None:
        """Reset all counters to zero."""
        with self._lock:
            self._counts.clear()


class TokenBucket:
    """Simple token-bucket rate limiter.

    Thread-safe. consume() busy-waits (with short sleeps) until a token is
    available or raises QuotaRateLimit if the wait would exceed max_wait_s.
    """

    def __init__(
        self,
        rate: float,
        capacity: float,
        *,
        max_wait_s: float = 5.0,
    ) -> None:
        """
        Args:
            rate:       Tokens refilled per second.
            capacity:   Maximum tokens in the bucket (burst size).
            max_wait_s: Max seconds to wait for a token before raising QuotaRateLimit.
        """
        if rate <= 0:
            raise ValueError(f"rate must be > 0, got {rate!r}")
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity!r}")
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self._max_wait_s = max_wait_s

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last = now

    def consume(self, tokens: float = 1.0, *, op: str = "") -> None:
        """Consume tokens, blocking until available or raising QuotaRateLimit.

        Raises:
            QuotaRateLimit: If wait would exceed max_wait_s.
        """
        deadline = time.monotonic() + self._max_wait_s
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait_needed = (tokens - self._tokens) / self._rate
            if time.monotonic() + wait_needed > deadline:
                raise QuotaRateLimit(
                    f"rate limit exceeded for op {op!r}; wait would be {wait_needed:.1f}s",
                    op=op,
                )
            time.sleep(min(wait_needed * 0.5, 0.05))


class QuotaGuard:
    """Wraps a callable with per-op counting and optional bucket gating.

    Usage::

        guard = QuotaGuard(counter, bucket=bucket)
        result = guard.call("drive.fetch", lambda: api.get(...))
    """

    def __init__(
        self,
        counter: PerOpCounter,
        bucket: TokenBucket | None = None,
    ) -> None:
        self._counter = counter
        self._bucket = bucket

    def call(self, op: str, fn: Callable[[], T]) -> T:
        """Gate fn() through the bucket (if set), count it, then invoke it."""
        if self._bucket is not None:
            self._bucket.consume(op=op)
        self._counter.increment(op)
        return fn()
