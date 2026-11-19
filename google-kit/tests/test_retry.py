"""Tests for google_kit.core.retry (unit + fault-injection)."""
import time
from unittest.mock import MagicMock

import pytest

from google_kit.core.errors import (
    Auth,
    Conflict,
    GoogleKitError,
    NotFound,
    Permission,
    QuotaRateLimit,
    Transient,
    Validation,
)
from google_kit.core.retry import retry, with_retry
from kp_mcp_testkit.faults import inject_fault_fn


def test_success_on_first_attempt() -> None:
    calls = []

    def fn() -> str:
        calls.append(1)
        return "ok"

    result = with_retry(fn, max_attempts=3, base_s=0, cap_s=0)
    assert result == "ok"
    assert len(calls) == 1


def test_retries_on_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    attempts = []

    def fn() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise Transient("temp")
        return "recovered"

    result = with_retry(fn, max_attempts=4, base_s=0, cap_s=0)
    assert result == "recovered"
    assert len(attempts) == 3


def test_retries_on_quota_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    attempts = []

    def fn() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise QuotaRateLimit("quota")
        return "ok"

    result = with_retry(fn, max_attempts=3, base_s=0, cap_s=0)
    assert result == "ok"
    assert len(attempts) == 2


def test_exhaustion_raises_last_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)

    def fn() -> None:
        raise Transient("always fails")

    with pytest.raises(Transient, match="always fails"):
        with_retry(fn, max_attempts=3, base_s=0, cap_s=0)


def test_no_retry_on_auth() -> None:
    calls = []

    def fn() -> None:
        calls.append(1)
        raise Auth("bad token")

    with pytest.raises(Auth):
        with_retry(fn, max_attempts=4, base_s=0, cap_s=0)
    assert len(calls) == 1


def test_no_retry_on_validation() -> None:
    calls = []

    def fn() -> None:
        calls.append(1)
        raise Validation("bad input")

    with pytest.raises(Validation):
        with_retry(fn, max_attempts=4, base_s=0, cap_s=0)
    assert len(calls) == 1


def test_no_retry_on_permission() -> None:
    def fn() -> None:
        raise Permission("denied")

    with pytest.raises(Permission):
        with_retry(fn, max_attempts=4, base_s=0, cap_s=0)


def test_no_retry_on_not_found() -> None:
    def fn() -> None:
        raise NotFound("missing")

    with pytest.raises(NotFound):
        with_retry(fn, max_attempts=4, base_s=0, cap_s=0)


def test_no_retry_on_conflict() -> None:
    def fn() -> None:
        raise Conflict("duplicate")

    with pytest.raises(Conflict):
        with_retry(fn, max_attempts=4, base_s=0, cap_s=0)


def test_retry_after_context_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    attempts = []

    def fn() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise Transient("wait", context={"retry_after": 7.5})
        return "ok"

    result = with_retry(fn, max_attempts=3, base_s=0, cap_s=0)
    assert result == "ok"
    assert slept == [7.5]


def test_retry_after_http_date_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime
    import email.utils

    slept: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)
    http_date = email.utils.format_datetime(future)

    attempts = []

    def fn() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise Transient("wait", context={"retry_after": http_date})
        return "ok"

    result = with_retry(fn, max_attempts=3, base_s=0, cap_s=0)
    assert result == "ok"
    assert len(slept) == 1
    assert 0 <= slept[0] <= 6


def test_obs_record_retry_called(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    obs = MagicMock()
    attempts = []

    def fn() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise Transient("t")
        return "done"

    with_retry(fn, max_attempts=4, base_s=0, cap_s=0, op="test.op", _obs=obs)
    assert obs.record_retry.call_count == 2


def test_decorator_form(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = []

    @retry(max_attempts=3, base_s=0, cap_s=0, op="test")
    def flaky(x: int) -> int:
        calls.append(x)
        if len(calls) < 2:
            raise Transient("retry me")
        return x * 2

    result = flaky(5)
    assert result == 10
    assert len(calls) == 2


def test_fault_injection_via_testkit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)

    def good_fetch() -> str:
        return "data"

    with inject_fault_fn(good_fetch, Transient, "injected", after_calls=1) as faulty_fetch:
        attempts = []

        def fn() -> str:
            return faulty_fetch()

        attempts.append(fn())
        with pytest.raises(Transient):
            attempts.append(fn())
    assert attempts == ["data"]
