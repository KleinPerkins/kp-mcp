"""Bounded exponential backoff with jitter for google-kit core (R23).

Retries ONLY Transient / QuotaRateLimit errors.
Never retries Auth / Validation / Permission / NotFound / Conflict.
Respects Retry-After header (seconds or HTTP-date) via error context.
"""
from __future__ import annotations

import email.utils
import functools
import math
import random
import time
from typing import Any, Callable, TypeVar

from google_kit.core.errors import (
    Auth,
    Conflict,
    NotFound,
    Permission,
    QuotaRateLimit,
    Transient,
    Validation,
)

T = TypeVar("T")

_NO_RETRY: tuple[type[Exception], ...] = (Auth, Validation, Permission, NotFound, Conflict)
_RETRYABLE: tuple[type[Exception], ...] = (Transient, QuotaRateLimit)

_DEFAULT_MAX_ATTEMPTS: int = 4
_DEFAULT_BASE_S: float = 1.0
_DEFAULT_CAP_S: float = 32.0


def _parse_retry_after(exc: Exception) -> float | None:
    """Extract a sleep duration from exc.context['retry_after'] if present.

    Accepts seconds (int/float) or an HTTP-date string.
    """
    ctx = getattr(exc, "context", {}) or {}
    raw = ctx.get("retry_after")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return max(0.0, float(raw))
    try:
        import datetime

        dt = email.utils.parsedate_to_datetime(str(raw))
        delay = (dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        return max(0.0, delay)
    except Exception:
        pass
    try:
        return max(0.0, float(raw))
    except Exception:
        return None


def _jitter_backoff(attempt: int, base: float, cap: float) -> float:
    """Full-jitter exponential backoff: uniform in [0, min(cap, base * 2^attempt)].

    Large attempt counts make ``base * 2^attempt`` overflow float; since the
    result is always clamped by ``cap``, an overflow simply means the ceiling is
    ``cap``. Guard the math so a high max_attempts never crashes the retry loop.
    """
    try:
        ceiling = min(cap, base * math.pow(2, attempt))
    except OverflowError:
        ceiling = cap
    return random.uniform(0.0, ceiling)


def with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_s: float = _DEFAULT_BASE_S,
    cap_s: float = _DEFAULT_CAP_S,
    op: str = "",
    _obs: Any = None,
) -> T:
    """Call fn(), retrying on Transient/QuotaRateLimit up to max_attempts total.

    Args:
        fn:           Zero-argument callable to invoke.
        max_attempts: Maximum total attempts (1 = no retry).
        base_s:       Backoff base in seconds.
        cap_s:        Backoff cap in seconds.
        op:           Operation name forwarded to observability.
        _obs:         Optional observability sink; receives record_retry(op, attempt, delay_s).

    Returns:
        Return value of fn() on the first successful attempt.

    Raises:
        The last retryable exception if all attempts are exhausted.
        Any non-retryable exception immediately.

    Raises:
        ValueError: If max_attempts < 1 (a config error — fn would never run).
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts!r}")
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except _NO_RETRY:
            raise
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt + 1 >= max_attempts:
                break
            delay = _parse_retry_after(exc)
            if delay is None:
                delay = _jitter_backoff(attempt, base_s, cap_s)
            if _obs is not None:
                try:
                    _obs.record_retry(op=op, attempt=attempt + 1, delay_s=delay)
                except Exception:
                    pass
            time.sleep(delay)
        except Exception:
            raise
    assert last_exc is not None
    raise last_exc


def retry(
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_s: float = _DEFAULT_BASE_S,
    cap_s: float = _DEFAULT_CAP_S,
    op: str = "",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that wraps a callable with with_retry.

    Usage::

        @retry(max_attempts=3, op="drive.fetch")
        def call_api() -> FetchResult:
            ...
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return with_retry(
                lambda: fn(*args, **kwargs),
                max_attempts=max_attempts,
                base_s=base_s,
                cap_s=cap_s,
                op=op or fn.__name__,
            )

        return wrapper

    return decorator
