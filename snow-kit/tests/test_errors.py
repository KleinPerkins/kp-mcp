"""Tests for snow_kit.core.errors."""
from __future__ import annotations

import pytest

from snow_kit.core.errors import (
    Auth,
    Permission,
    SnowKitError,
    Timeout,
    Transient,
    Unknown,
    Validation,
    classify_connector,
    redact_message,
)


def test_mcp_payload_shape() -> None:
    exc = Transient("network blip", op="query.execute")
    payload = exc.to_mcp_payload()
    assert payload == {
        "error": "Transient",
        "message": "network blip",
        "op": "query.execute",
    }


def test_redact_message_scrubs_secrets() -> None:
    text = "login failed password=supersecret token=abc123"
    assert "supersecret" not in redact_message(text)
    assert "abc123" not in redact_message(text)


def test_classify_permission_error() -> None:
    exc = classify_connector(PermissionError("read-only"), op="query.execute")
    assert isinstance(exc, Permission)
    assert exc.op == "query.execute"


def test_classify_value_error() -> None:
    exc = classify_connector(ValueError("bad identifier"), op="catalog.list_tables")
    assert isinstance(exc, Validation)


def test_classify_sqlstate_auth() -> None:
    class _Err(Exception):
        sqlstate = "28000"

    exc = classify_connector(_Err("authentication failed"), op="query.execute")
    assert isinstance(exc, Auth)


def test_classify_timeout_message() -> None:
    exc = classify_connector(Exception("statement timeout after 25s"), op="query.execute")
    assert isinstance(exc, Timeout)


def test_classify_unknown() -> None:
    exc = classify_connector(RuntimeError("something odd"), op="query.execute")
    assert isinstance(exc, Unknown)


def test_snowkit_error_is_exception() -> None:
    exc = Validation("bad input")
    assert isinstance(exc, Exception)
    assert isinstance(exc, SnowKitError)
    assert isinstance(exc, ValueError)
