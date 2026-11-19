"""MCP timeout/error contract tests for snow-kit."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from snow_kit.core.errors import Transient
from snow_kit.mcp import _invoke_tool_sync, build_mcp_server
from snow_kit.registry import get

_TRACEBACK_MARKER = "Traceback (most recent call last)"


def _assert_structured_mcp_error(result: Any) -> dict[str, Any]:
    if isinstance(result, str):
        text = result
    else:
        assert result.isError is True
        text = result.content[0].text
    assert _TRACEBACK_MARKER not in text
    payload = json.loads(text)
    assert payload.get("error")
    assert payload.get("message")
    assert "data" not in payload
    return payload


def test_mcp_write_hidden_returns_flag_disabled_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNOW_KIT_ENABLE_WRITE", raising=False)
    payload = _assert_structured_mcp_error(
        _invoke_tool_sync(get("query.execute_write"), {"query": "INSERT INTO DEMO VALUES (1)"})
    )
    assert payload["error"] == "FlagDisabledError"
    assert "SNOW_KIT_ENABLE_WRITE" in payload["message"]
    assert payload["op"] == "query.execute_write"


def test_mcp_unknown_argument_is_structured() -> None:
    payload = _assert_structured_mcp_error(
        _invoke_tool_sync(get("query.execute"), {"query": "SELECT 1", "bogus_param": 1})
    )
    assert payload["error"] == "Validation"
    assert "Unknown argument" in payload["message"]


def test_mcp_read_only_violation_is_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNOW_KIT_ENABLE_WRITE", raising=False)
    payload = _assert_structured_mcp_error(
        _invoke_tool_sync(get("query.execute"), {"query": "INSERT INTO DEMO VALUES (1)"})
    )
    assert payload["error"] == "Permission"
    assert "read-only" in payload["message"].lower()


def test_mcp_snowflake_failure_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingSession:
        def execute(self, *_args: Any, **_kwargs: Any) -> None:
            raise Transient("network unavailable", op="query.execute")

    monkeypatch.setattr("snow_kit.services.query.core.default_session", lambda: _FailingSession())
    payload = _assert_structured_mcp_error(
        _invoke_tool_sync(get("query.execute"), {"query": "SELECT 1"})
    )
    assert payload["error"] == "Transient"
    assert payload["op"] == "query.execute"


def test_mcp_tool_timeout_is_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp.types import CallToolRequest, CallToolRequestParams

    monkeypatch.setenv("SNOW_KIT_TOOL_TIMEOUT", "1")

    def _slow_execute(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        import time

        time.sleep(2)
        return {}

    monkeypatch.setattr("snow_kit.mcp._invoke_tool_sync", _slow_execute)

    server = build_mcp_server()
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="query_execute", arguments={"query": "SELECT 1"}),
        )
        return await handler(req)

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    payload = _assert_structured_mcp_error(root)
    assert payload["error"] == "Timeout"
    assert "timed out" in payload["message"].lower()


def test_mcp_unknown_tool_does_not_emit_traceback() -> None:
    from mcp.types import CallToolRequest, CallToolRequestParams

    server = build_mcp_server()
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="this_tool_does_not_exist", arguments={}),
        )
        return await handler(req)

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    assert root.isError is True
    text = root.content[0].text if root.content else str(root)
    assert _TRACEBACK_MARKER not in text
