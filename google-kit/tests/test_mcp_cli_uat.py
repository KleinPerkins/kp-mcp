"""Operator-style UAT coverage for the google-kit CLI and MCP adapter.

These tests intentionally use no live Google network. CLI cases either resolve
help text or fail before auth/service construction; MCP cases inject mock
services through ``build_mcp_server``.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

import google_kit  # noqa: F401 - triggers registration
from google_kit.cli import main as cli_main
from google_kit.mcp import build_mcp_server
from kp_mcp_testkit.mock_google import MockGoogleService


def _mcp_call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=arguments),
        )
        return await handler(req)

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    return json.loads(root.content[0].text)


def _mcp_tools(server: Any) -> list[Any]:
    handler = server.request_handlers[ListToolsRequest]

    async def _run() -> Any:
        return await handler(ListToolsRequest(method="tools/list", params=None))

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    return list(root.tools)


def test_cli_accepts_global_format_after_help_intent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_main(["help", "send", "email", "--format", "text"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "google-kit gmail send" in out
    assert '"matches"' not in out


def test_cli_bad_json_flag_names_the_flag_and_exits_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    called: list[str] = []

    def factory(op_name: str, *, profile: str | None = None) -> Any:
        called.append(op_name)
        raise AssertionError("validation should happen before service construction")

    with pytest.raises(SystemExit) as exc:
        cli_main(["gmail", "list", "--label-ids", "not-json"], _service_factory=factory)

    assert exc.value.code == 7
    err = capsys.readouterr().err
    assert "Invalid JSON for --label-ids" in err
    assert "'[\"value\"]'" in err
    assert "line 1 column" not in err
    assert called == []


def test_cli_constraint_error_is_actionable_validation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_main(["tasks", "list-lists", "--max-results", "0"])

    assert exc.value.code == 7
    err = capsys.readouterr().err
    assert "Invalid arguments for tasks.list_lists" in err
    assert "--max-results: Input should be greater than or equal to 1" in err
    assert "errors.pydantic.dev" not in err


def test_cli_write_gate_mentions_specific_and_umbrella_flags(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
    monkeypatch.delenv("GOOGLE_KIT_ENABLE_WRITES", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli_main(["tasks", "create", "--title", "UAT task"])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "tasks.create is not authorized" in err
    assert "auth grant tasks.create" in err
    assert "GOOGLE_KIT_ENABLE_TASKS_WRITE=1" in err
    assert "GOOGLE_KIT_ENABLE_WRITES=1" in err


def test_mcp_dispatch_with_mock_service_returns_json_envelope() -> None:
    svc = MockGoogleService(
        responses={
            ("tasklists", "list"): {
                "items": [{"id": "t1", "title": "Work", "kind": "tasks#taskList"}]
            }
        }
    )
    server = build_mcp_server(_service_factory=lambda op_name: svc)

    payload = _mcp_call(server, "tasks_list_lists", {"max_results": 1})

    assert payload["data"]["count"] == 1
    assert payload["data"]["task_lists"][0]["title"] == "Work"
    assert payload["meta"]["op"] == "tasks.list_lists"


def test_mcp_validation_error_is_structured_and_does_not_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_GMAIL_WRITE", "1")
    called: list[str] = []

    def factory(op_name: str, *, profile: str | None = None) -> Any:
        called.append(op_name)
        raise AssertionError("validation should happen before service construction")

    server = build_mcp_server(_service_factory=factory)

    payload = _mcp_call(
        server,
        "gmail_batch_modify",
        {"ids": [], "add_label_ids": ["Label_1"], "remove_label_ids": []},
    )

    assert payload["error"] == "Validation"
    assert payload["op"] == "gmail.batch_modify"
    assert "ids must contain at least one message ID" in payload["message"]
    assert "errors.pydantic.dev" not in payload["message"]
    assert called == []


def test_mcp_write_tool_description_explains_gate() -> None:
    server = build_mcp_server()
    tools = {tool.name: tool for tool in _mcp_tools(server)}

    description = tools["tasks_create"].description
    assert description is not None
    assert "requires authorization" in description
    assert "auth grant tasks.create" in description
    assert "GOOGLE_KIT_ENABLE_TASKS_WRITE=1" in description
    assert "GOOGLE_KIT_ENABLE_WRITES=1" in description
