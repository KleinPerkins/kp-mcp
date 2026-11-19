"""MCP exposure tests for hidden write posture operations."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from snow_kit.mcp import _build_tool_map, _invoke_tool_sync, _visible_specs, build_mcp_server
from snow_kit.core.intents import resolve_help, visible_specs
from snow_kit.registry import all_specs, get


def _payload(result: Any) -> dict[str, Any]:
    text = result if isinstance(result, str) else result.content[0].text
    return json.loads(text)


def test_write_tools_hidden_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNOW_KIT_ENABLE_WRITE", raising=False)

    names = {spec.name for spec in _visible_specs(all_specs())}

    assert "query.execute" in names
    assert "query.execute_write" not in names


def test_write_tools_visible_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNOW_KIT_ENABLE_WRITE", "1")

    names = {spec.name for spec in _visible_specs(all_specs())}

    assert "query.execute_write" in names


def test_read_only_mode_ignores_poisoned_write_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNOW_KIT_ENABLE_WRITE", "1")

    names = {spec.name for spec in _visible_specs(all_specs(), read_only=True)}

    assert "query.execute" in names
    assert "query.execute_write" not in names


def test_direct_write_call_rejected_when_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNOW_KIT_ENABLE_WRITE", raising=False)

    payload = _payload(
        _invoke_tool_sync(
            get("query.execute_write"),
            {"query": "INSERT INTO EXAMPLE_DB.SCRATCH.DEMO VALUES (1)"},
        )
    )

    assert payload["error"] == "FlagDisabledError"
    assert "SNOW_KIT_ENABLE_WRITE" in payload["message"]


def test_mcp_tool_names_are_injective() -> None:
    tool_map = _build_tool_map(all_specs())

    assert "query_execute" in tool_map
    assert tool_map["catalog_check_write_access"].name == "catalog.check_write_access"


def test_help_name_is_reserved() -> None:
    with pytest.raises(ValueError, match="reserved MCP tool name"):
        _build_tool_map([SimpleNamespace(name="help")])


def test_cli_and_mcp_share_visibility_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SNOW_KIT_ENABLE_WRITE", raising=False)
    expected = [spec.name for spec in visible_specs(all_specs())]
    assert [spec.name for spec in _visible_specs(all_specs())] == expected
    assert all(
        match.operation != "query.execute_write"
        for match in resolve_help("execute snowflake write").matches
    )


def test_call_tool_returns_json_when_write_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp.types import CallToolRequest, CallToolRequestParams

    monkeypatch.delenv("SNOW_KIT_ENABLE_WRITE", raising=False)
    server = build_mcp_server()
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="query_execute_write",
                arguments={"query": "INSERT INTO DEMO VALUES (1)"},
            ),
        )
        return await handler(req)

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    assert root.isError is True
    payload = json.loads(root.content[0].text)

    assert payload["error"] == "FlagDisabledError"
    assert "SNOW_KIT_ENABLE_WRITE" in payload["message"]


def test_read_only_server_rejects_direct_write_under_poisoned_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.types import CallToolRequest, CallToolRequestParams

    monkeypatch.setenv("SNOW_KIT_ENABLE_WRITE", "1")
    server = build_mcp_server(read_only=True)
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="query_execute_write",
                arguments={"query": "INSERT INTO DEMO VALUES (1)"},
            ),
        )
        return await handler(req)

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    assert root.isError is True
    payload = json.loads(root.content[0].text)

    assert payload["error"] == "FlagDisabledError"
    assert "fail-closed read-only" in payload["message"]
