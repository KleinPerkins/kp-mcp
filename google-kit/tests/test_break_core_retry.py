"""Adversarial edge-case tests for google_kit.core.retry."""
from __future__ import annotations

import pytest

from google_kit.core.errors import Transient
from google_kit.core.retry import _jitter_backoff, with_retry


class TestBackoffOverflow:
    """base * 2^attempt overflows float for large attempt; must clamp to cap."""

    def test_large_attempt_does_not_overflow(self) -> None:
        delay = _jitter_backoff(2000, base=1.0, cap=32.0)
        assert 0.0 <= delay <= 32.0

    def test_jitter_within_bounds_small_attempt(self) -> None:
        for attempt in range(0, 6):
            delay = _jitter_backoff(attempt, base=1.0, cap=32.0)
            ceiling = min(32.0, 1.0 * (2 ** attempt))
            assert 0.0 <= delay <= ceiling

    def test_retry_loop_survives_high_max_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("time.sleep", lambda _: None)
        attempts = []

        def fn() -> str:
            attempts.append(1)
            if len(attempts) < 60:
                raise Transient("flaky")
            return "ok"

        # Without the overflow guard, deep attempts would raise OverflowError.
        result = with_retry(fn, max_attempts=200, base_s=1.0, cap_s=32.0)
        assert result == "ok"


class TestInvalidMaxAttempts:
    """max_attempts < 1 must fail loud (ValueError), not AssertionError / silent."""

    def test_zero_max_attempts_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            with_retry(lambda: 1, max_attempts=0)

    def test_negative_max_attempts_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            with_retry(lambda: 1, max_attempts=-5)

    def test_one_max_attempt_runs_once(self) -> None:
        calls = []

        def fn() -> str:
            calls.append(1)
            return "ok"

        assert with_retry(fn, max_attempts=1) == "ok"
        assert len(calls) == 1
