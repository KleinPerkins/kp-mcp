"""Retry-After header wiring (core/client → core/retry).

The retry layer already honors ``exc.context['retry_after']`` (see
``test_retry.py``), and the docstrings of ``core/client``, ``core/errors``, and
``core/retry`` all promise that google-kit "respects Retry-After". The missing
link was the production classify path: ``_classify_exception`` parsed the HTTP
status and message but never extracted the ``Retry-After`` response header into
the taxonomy error's ``context``, so a real 429/503 carrying ``Retry-After``
silently fell back to jitter backoff instead of the server-specified delay.

These tests pin the end-to-end contract: the header must reach the error
context, and ``execute_api_call`` must sleep for the header-specified duration.
No live network — a fake ``HttpError`` is constructed in-process.
"""
from __future__ import annotations

import json
from typing import Any

import pytest


def _http_error(status: int, *, retry_after: str | None = None) -> Any:
    """Build a googleapiclient HttpError with an optional Retry-After header."""
    import httplib2
    from googleapiclient.errors import HttpError

    headers: dict[str, Any] = {"status": status}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    resp = httplib2.Response(headers)
    content = json.dumps({"error": {"message": "slow down"}}).encode("utf-8")
    return HttpError(resp, content)


class TestClassifyExtractsRetryAfter:
    def test_429_seconds_header_reaches_context(self) -> None:
        from google_kit.core.client import _classify_exception
        from google_kit.core.errors import QuotaRateLimit

        exc = _classify_exception(_http_error(429, retry_after="30"), op="x.y")
        assert isinstance(exc, QuotaRateLimit)
        assert exc.context.get("retry_after") == "30"

    def test_503_http_date_header_reaches_context(self) -> None:
        import datetime
        import email.utils

        from google_kit.core.client import _classify_exception
        from google_kit.core.errors import Transient

        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)
        http_date = email.utils.format_datetime(future)
        exc = _classify_exception(_http_error(503, retry_after=http_date), op="x.y")
        assert isinstance(exc, Transient)
        assert exc.context.get("retry_after") == http_date

    def test_no_header_leaves_context_clean(self) -> None:
        from google_kit.core.client import _classify_exception

        exc = _classify_exception(_http_error(429), op="x.y")
        assert "retry_after" not in exc.context

    def test_408_http_error_classified_transient(self) -> None:
        """A real HTTP 408 must classify as Transient so it is retried."""
        from google_kit.core.client import _classify_exception
        from google_kit.core.errors import Transient

        exc = _classify_exception(_http_error(408), op="x.y")
        assert isinstance(exc, Transient)

    def test_410_http_error_classified_unknown(self) -> None:
        """A real HTTP 410 Gone must classify as Unknown (not retried)."""
        from google_kit.core.client import _classify_exception
        from google_kit.core.errors import Unknown

        exc = _classify_exception(_http_error(410), op="x.y")
        assert isinstance(exc, Unknown)

    def test_408_is_retried_by_execute_api_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """408 is retryable end-to-end: a first 408 then success returns ok."""
        monkeypatch.setattr("time.sleep", lambda s: None)
        from google_kit.core.client import execute_api_call

        calls: list[int] = []

        def api_fn() -> dict[str, Any]:
            calls.append(1)
            if len(calls) == 1:
                raise _http_error(408)
            return {"ok": True}

        out = execute_api_call(api_fn, op="x.y", posture="read", max_attempts=3)
        assert out == {"ok": True}
        assert len(calls) == 2


class TestExecuteApiCallRespectsRetryAfter:
    def test_retry_sleeps_for_header_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

        from google_kit.core.client import execute_api_call

        calls: list[int] = []

        def api_fn() -> dict[str, Any]:
            calls.append(1)
            if len(calls) == 1:
                raise _http_error(503, retry_after="3")
            return {"ok": True}

        out = execute_api_call(api_fn, op="x.y", posture="read", max_attempts=3)
        assert out == {"ok": True}
        assert slept == [3.0], (
            "execute_api_call must respect the server's Retry-After header "
            f"(expected a single 3.0s sleep, got {slept!r})"
        )
