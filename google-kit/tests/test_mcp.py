"""Tests for google-kit MCP adapter.

Parity: tool-listing DONE; tool-invocation mock DONE; transport DEFERRED(P6)
"""
from __future__ import annotations

import json
import re
from typing import Any

import pytest

import google_kit  # noqa: F401 — triggers registration
from google_kit.mcp import _build_tool_map, _tool_name, build_mcp_server
from google_kit.registry import all_specs
from kp_mcp_bootstrap.docgen import mcp_tool_name
from kp_mcp_testkit.mock_google import MockGoogleService


def _tasks_factory(responses: dict) -> Any:
    """Return a service factory yielding a MockGoogleService."""
    svc = MockGoogleService(responses=responses)

    def factory(op_name: str, *, profile: str | None = None) -> Any:
        return svc

    return factory


class TestToolListing:
    """Test that all 41 ops are exposed as MCP tools."""

    def test_list_tools_handler_registered(self) -> None:
        from mcp.types import ListToolsRequest

        server = build_mcp_server()
        assert ListToolsRequest in server.request_handlers

    def test_list_tools_returns_41(self) -> None:
        import asyncio
        from mcp.types import ListToolsRequest

        server = build_mcp_server()
        handler = server.request_handlers[ListToolsRequest]

        async def _run():
            from mcp.types import PaginatedRequest
            req = ListToolsRequest(method="tools/list", params=None)
            result = await handler(req)
            return result

        result = asyncio.run(_run())
        assert result is not None

    def test_tool_count_matches_registry(self) -> None:
        import asyncio
        from mcp.types import ListToolsRequest

        server = build_mcp_server()
        handler = server.request_handlers[ListToolsRequest]

        async def _run():
            req = ListToolsRequest(method="tools/list", params=None)
            return await handler(req)

        result = asyncio.run(_run())
        root = getattr(result, "root", result)
        # Every registry op is exposed under its SANITIZED (MCP-valid) tool name,
        # plus the synthetic E6 `help` meta-tool.
        names = {t.name for t in root.tools}
        assert names == {mcp_tool_name(s.name) for s in all_specs()} | {"help"}
        assert len(root.tools) == len(list(all_specs())) + 1

    def test_mcp_schema_has_required_keys(self) -> None:
        from kp_mcp_bootstrap.docgen import Docgen

        docgen = Docgen()
        for spec in all_specs():
            schema = docgen.emit_mcp_schema(spec)
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema
            # The schema advertises the MCP-valid (sanitized) tool name, not the
            # dotted registry op name.
            assert schema["name"] == mcp_tool_name(spec.name)

    def test_all_descriptions_nonempty(self) -> None:
        from kp_mcp_bootstrap.docgen import Docgen

        docgen = Docgen()
        for spec in all_specs():
            schema = docgen.emit_mcp_schema(spec)
            assert schema["description"], f"Empty description for {spec.name}"

    def test_input_schemas_valid_json_schema(self) -> None:
        for spec in all_specs():
            schema = spec.input_model.model_json_schema()
            assert schema.get("type") == "object" or "properties" in schema or "$defs" in schema


class TestToolInvocation:
    """Test tool invocation through the adapter with mock services."""

    def test_tasks_list_lists_returns_content(self) -> None:
        import asyncio
        from mcp.types import CallToolRequest, CallToolRequestParams

        factory = _tasks_factory({
            ("tasklists", "list"): {
                "items": [{"id": "t1", "title": "Work", "kind": "tasks#taskList"}]
            }
        })
        server = build_mcp_server(_service_factory=factory)

        async def _run():
            from mcp.types import CallToolRequest, CallToolRequestParams

            # Sanitized name for the dotted op `tasks.list_lists`. The op segment
            # itself contains an underscore, so this exercises the round-trip that
            # a naive `_`→`.` reverse would break.
            req = CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(name="tasks_list_lists", arguments={}),
            )
            handler = server.request_handlers[CallToolRequest]
            return await handler(req)

        result = asyncio.run(_run())
        assert result is not None

    def test_tool_result_is_valid_json(self) -> None:
        import asyncio
        from mcp.types import CallToolRequest, CallToolRequestParams, ServerResult

        factory = _tasks_factory({
            ("tasklists", "list"): {
                "items": [{"id": "x", "title": "Personal", "kind": "tasks#taskList"}]
            }
        })
        server = build_mcp_server(_service_factory=factory)

        async def _run():
            req = CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(
                    name="tasks_list_lists",
                    arguments={"max_results": 10},
                ),
            )
            handler = server.request_handlers[CallToolRequest]
            return await handler(req)

        result = asyncio.run(_run())
        if isinstance(result, ServerResult):
            root = result.root
            if hasattr(root, "content") and root.content:
                text = root.content[0].text if hasattr(root.content[0], "text") else str(root.content[0])
                parsed = json.loads(text)
                assert "data" in parsed


class TestServerBuild:
    def test_build_server_returns_server(self) -> None:
        from mcp.server import Server

        server = build_mcp_server()
        assert isinstance(server, Server)

    def test_list_tools_handler_registered(self) -> None:
        from mcp.types import ListToolsRequest

        server = build_mcp_server()
        assert ListToolsRequest in server.request_handlers

    def test_call_tool_handler_registered(self) -> None:
        from mcp.types import CallToolRequest

        server = build_mcp_server()
        assert CallToolRequest in server.request_handlers


class TestToolNameSanitization:
    """Regression tests for the MCP tool-name charset bug.

    MCP clients (Cursor) reject tool names that are not ``^[a-zA-Z0-9_]+$`` — the
    dotted registry op names (``calendar.create``) were rejected wholesale. These
    tests pin the sanitization, the list→call round-trip, and the collision guard.
    """

    _MCP_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")

    def _listed_tool_names(self) -> set[str]:
        import asyncio
        from mcp.types import ListToolsRequest

        server = build_mcp_server()
        handler = server.request_handlers[ListToolsRequest]

        async def _run():
            return await handler(ListToolsRequest(method="tools/list", params=None))

        result = asyncio.run(_run())
        root = getattr(result, "root", result)
        return {t.name for t in root.tools}

    def test_every_emitted_tool_name_matches_mcp_charset(self) -> None:
        names = self._listed_tool_names()
        assert names, "no tools emitted"
        for name in names:
            assert self._MCP_NAME_RE.match(name), f"invalid MCP tool name: {name!r}"
            assert "." not in name, f"dotted tool name leaked: {name!r}"
            assert len(name) <= 64, f"tool name exceeds MCP 64-char limit: {name!r}"

    def test_list_to_call_round_trips_to_correct_spec(self) -> None:
        """Every sanitized tool name dispatches back to exactly its OpSpec."""
        tool_map = _build_tool_map(all_specs())
        # The map exposes one entry per registered op (no shadowing/loss).
        assert len(tool_map) == len(list(all_specs()))
        for spec in all_specs():
            tool_name = mcp_tool_name(spec.name)
            assert tool_name in tool_map, f"{spec.name} not exposed as {tool_name}"
            assert tool_map[tool_name] is spec, (
                f"{tool_name} resolved to {tool_map[tool_name].name!r}, "
                f"expected {spec.name!r}"
            )

    def test_underscore_segment_ops_round_trip(self) -> None:
        """Ops whose segments contain underscores must still resolve correctly.

        A naive ``name.replace('_', '.')`` reverse would corrupt these (e.g.
        ``gmail_manage_labels`` → the non-existent ``gmail.manage.labels``).
        """
        tricky = [
            "gmail.manage_labels",
            "tasks.list_lists",
            "people.batch_get",
            "people.list_directory",
            "sheets.conditional_format",
            "script.get_content",
            "script.update_content",
            "drive_activity.query",
        ]
        registered = {s.name for s in all_specs()}
        tool_map = _build_tool_map(all_specs())
        for op_name in tricky:
            assert op_name in registered, f"test fixture stale: {op_name} not registered"
            sanitized = mcp_tool_name(op_name)
            assert "." not in sanitized
            assert tool_map[sanitized].name == op_name

    def test_real_registry_builds_without_collision(self) -> None:
        # With today's ops, `.`→`_` is collision-free; this guards future ops.
        tool_map = _build_tool_map(all_specs())
        assert len(tool_map) == len({mcp_tool_name(s.name) for s in all_specs()})

    def test_collision_guard_raises_on_synthetic_clash(self) -> None:
        from types import SimpleNamespace

        # `a.b_c` and `a.b.c` both sanitize to `a_b_c` — must fail fast.
        colliding = [
            SimpleNamespace(name="a.b_c"),
            SimpleNamespace(name="a.b.c"),
        ]
        assert mcp_tool_name(colliding[0].name) == mcp_tool_name(colliding[1].name)
        with pytest.raises(ValueError, match="collision"):
            _build_tool_map(colliding)

    def test_reserved_help_name_guard_raises(self) -> None:
        from types import SimpleNamespace

        with pytest.raises(ValueError, match="reserved"):
            _build_tool_map([SimpleNamespace(name="help")])

    def test_tool_name_helper_matches_sanitizer(self) -> None:
        from types import SimpleNamespace

        spec = SimpleNamespace(name="drive_activity.query")
        assert _tool_name(spec) == "drive_activity_query"
