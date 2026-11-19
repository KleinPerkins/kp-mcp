from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams
from kp_mcp_testkit.mock_google import MockGoogleService

from google_kit.mcp import _build_tool_map, build_mcp_server


def test_mcp_tool_map_rejects_invalid_sanitized_names() -> None:
    with pytest.raises(ValueError, match="invalid MCP tool name"):
        _build_tool_map([SimpleNamespace(name="!!!")])


def test_mcp_tool_map_rejects_empty_sanitized_names() -> None:
    with pytest.raises(ValueError, match="invalid MCP tool name"):
        _build_tool_map([SimpleNamespace(name="")])


def test_mcp_call_rejects_unknown_arguments_before_dispatch() -> None:
    svc = MockGoogleService(
        responses={
            ("tasklists", "list"): {
                "items": [{"id": "t1", "title": "Work", "kind": "tasks#taskList"}]
            }
        }
    )
    called: list[str] = []

    def factory(op_name: str, *, profile: str | None = None) -> Any:
        called.append(op_name)
        return svc

    server = build_mcp_server(_service_factory=factory)
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(
                name="tasks_list_lists",
                arguments={"max_results": 1, "max_resultz": 999},
            ),
        )
        return await handler(req)

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    assert root.isError is False
    payload = json.loads(root.content[0].text)
    assert payload["error"] == "Validation"
    assert "Unknown argument" in payload["message"]
    assert "Allowed arguments" in payload["message"]
    assert called == []
