"""Tests for google_kit.core.errors."""
import pytest

from google_kit.core.errors import (
    Auth,
    Conflict,
    GoogleKitError,
    NotFound,
    Permission,
    QuotaRateLimit,
    Transient,
    Unknown,
    Validation,
    classify,
)


def test_base_exit_code() -> None:
    assert GoogleKitError("boom").to_exit_code() == 1


def test_subclass_exit_codes() -> None:
    assert Transient("t").to_exit_code() == 2
    assert Auth("a").to_exit_code() == 3
    assert QuotaRateLimit("q").to_exit_code() == 4
    assert Permission("p").to_exit_code() == 5
    assert NotFound("n").to_exit_code() == 6
    assert Validation("v").to_exit_code() == 7
    assert Conflict("c").to_exit_code() == 8
    assert Unknown("u").to_exit_code() == 9


def test_mcp_payload_shape() -> None:
    exc = Transient("transient error", op="drive.fetch")
    payload = exc.to_mcp_payload()
    assert payload["error"] == "Transient"
    assert payload["message"] == "transient error"
    assert payload["op"] == "drive.fetch"
    assert "traceback" not in payload
    assert len(payload) == 3


def test_classify_known_statuses() -> None:
    cases = [
        (400, Validation),
        (401, Auth),
        (403, Permission),
        (404, NotFound),
        (408, Transient),
        (409, Conflict),
        (429, QuotaRateLimit),
        (500, Transient),
        (502, Transient),
        (503, Transient),
        (504, Transient),
    ]
    for code, expected_cls in cases:
        exc = classify(code, op="test.op")
        assert isinstance(exc, expected_cls), f"status {code} → expected {expected_cls.__name__}"
        assert exc.op == "test.op"


def test_classify_408_is_transient() -> None:
    """HTTP 408 Request Timeout is transient and should be retried."""
    exc = classify(408, "request timeout", op="drive.search")
    assert isinstance(exc, Transient)


def test_classify_410_is_unknown_not_retried() -> None:
    """HTTP 410 Gone is permanent — classified Unknown (not retried)."""
    exc = classify(410, "gone", op="drive.changes")
    assert isinstance(exc, Unknown)


def test_classify_unknown_status() -> None:
    exc = classify(418, "I'm a teapot")
    assert isinstance(exc, Unknown)
    assert "418" in exc.message or "teapot" in exc.message.lower()


def test_classify_reason_used_in_message() -> None:
    exc = classify(503, "service unavailable")
    assert "service unavailable" in exc.message


def test_context_stored() -> None:
    ctx = {"retry_after": 30}
    exc = Transient("t", op="drive.list", context=ctx)
    assert exc.context == ctx
    assert exc.op == "drive.list"


def test_is_exception_subclass() -> None:
    exc = Validation("bad input")
    assert isinstance(exc, Exception)
    assert isinstance(exc, GoogleKitError)
