"""Tests for google_kit.core.quota (unit + fault-injection)."""
import time

import pytest

from google_kit.core.errors import QuotaRateLimit
from google_kit.core.quota import PerOpCounter, QuotaGuard, TokenBucket
from kp_mcp_testkit.faults import inject_fault_fn


def test_counter_increments() -> None:
    c = PerOpCounter()
    assert c.get("drive.fetch") == 0
    assert c.increment("drive.fetch") == 1
    assert c.increment("drive.fetch") == 2
    assert c.get("drive.fetch") == 2


def test_counter_snapshot() -> None:
    c = PerOpCounter()
    c.increment("a")
    c.increment("b")
    c.increment("a")
    snap = c.snapshot()
    assert snap == {"a": 2, "b": 1}


def test_counter_reset() -> None:
    c = PerOpCounter()
    c.increment("x")
    c.reset()
    assert c.snapshot() == {}


def test_token_bucket_allows_initial_capacity() -> None:
    bucket = TokenBucket(rate=1.0, capacity=5.0, max_wait_s=0.01)
    for _ in range(5):
        bucket.consume()


def test_token_bucket_raises_on_exhaustion() -> None:
    bucket = TokenBucket(rate=0.001, capacity=1.0, max_wait_s=0.01)
    bucket.consume()
    with pytest.raises(QuotaRateLimit):
        bucket.consume(op="test.op")


def test_token_bucket_invalid_rate() -> None:
    with pytest.raises(ValueError, match="rate"):
        TokenBucket(rate=0, capacity=1.0)


def test_token_bucket_invalid_capacity() -> None:
    with pytest.raises(ValueError, match="capacity"):
        TokenBucket(rate=1.0, capacity=0)


def test_quota_guard_counts_calls() -> None:
    counter = PerOpCounter()
    guard = QuotaGuard(counter)
    guard.call("drive.fetch", lambda: None)
    guard.call("drive.fetch", lambda: None)
    assert counter.get("drive.fetch") == 2


def test_quota_guard_with_bucket_raises_on_exhaustion() -> None:
    counter = PerOpCounter()
    bucket = TokenBucket(rate=0.001, capacity=1.0, max_wait_s=0.01)
    guard = QuotaGuard(counter, bucket=bucket)
    guard.call("op", lambda: None)
    with pytest.raises(QuotaRateLimit):
        guard.call("op", lambda: None)
    assert counter.get("op") == 1


def test_quota_guard_propagates_fn_result() -> None:
    counter = PerOpCounter()
    guard = QuotaGuard(counter)
    result = guard.call("x", lambda: 42)
    assert result == 42


def test_fault_injection_into_quota_guard() -> None:
    counter = PerOpCounter()
    guard = QuotaGuard(counter)

    def failing_fn() -> None:
        raise RuntimeError("injected")

    with inject_fault_fn(failing_fn, RuntimeError, "injected") as faulty:
        with pytest.raises(RuntimeError, match="injected"):
            guard.call("x", faulty)
    assert counter.get("x") == 1
