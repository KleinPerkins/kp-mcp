"""Focused native MCP metadata and structured-output contract tests."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
)

from snow_kit import __version__
from snow_kit.core.config import CONFIG_PATH_ENV, WRITE_FLAG
from snow_kit.mcp import build_mcp_server
from snow_kit.mcp.metadata import discovery_cues
from snow_kit.mcp.resources import SOURCE_STATUS_URI
from snow_kit.registry import all_specs


def _root(result: Any) -> Any:
    return getattr(result, "root", result)


def _list_tool_sequence(server: Any) -> list[Any]:
    handler = server.request_handlers[ListToolsRequest]
    result = asyncio.run(handler(ListToolsRequest(method="tools/list")))
    return list(_root(result).tools)


def _list_tools(server: Any) -> dict[str, Any]:
    return {tool.name: tool for tool in _list_tool_sequence(server)}


def test_server_advertises_version_instructions_and_resource_capabilities() -> None:
    server = build_mcp_server()

    options = server.create_initialization_options()

    assert options.server_name == "snow-kit"
    assert options.server_version == __version__
    assert "Inspect relevant catalog metadata before querying" in options.instructions
    assert "resources are optional references" in options.instructions
    assert "Call help first" in options.instructions
    assert "deterministic server-side" in options.instructions
    assert "model initially selects help remains model-dependent" in options.instructions
    assert "proves approved provenance, not semantic relevance" in options.instructions
    assert options.capabilities.resources is not None
    assert options.capabilities.resources.subscribe is False
    assert options.capabilities.resources.listChanged is False


def test_tools_expose_output_schema_descriptions_and_conservative_annotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNOW_KIT_ENABLE_WRITE", "1")
    tools = _list_tools(build_mcp_server())

    help_tool = tools["help"]
    assert help_tool.inputSchema["required"] == ["intent"]
    assert help_tool.outputSchema["properties"]["workflow_recommendations"]
    assert help_tool.annotations.readOnlyHint is True
    assert help_tool.annotations.destructiveHint is False
    assert help_tool.annotations.idempotentHint is True
    assert help_tool.annotations.openWorldHint is False
    assert "performs no Snowflake query or context retrieval" in help_tool.description

    execute = tools["query_execute"]
    assert execute.outputSchema["properties"]["data"]
    assert "max_rows caps rows returned to the client only" in execute.description
    assert execute.annotations.readOnlyHint is False
    assert execute.annotations.idempotentHint is None
    assert execute.annotations.destructiveHint is False
    assert execute.annotations.openWorldHint is True

    describe = tools["catalog_describe_table"]
    assert describe.annotations.readOnlyHint is True
    assert describe.annotations.idempotentHint is True

    preview = tools["catalog_preview_table"]
    assert "sensitive row values" in preview.description
    assert "catalog_describe_table first" in preview.description

    write = tools["query_execute_write"]
    assert "SNOW_KIT_ENABLE_WRITE=1" in write.description
    assert write.annotations.readOnlyHint is False
    assert write.annotations.destructiveHint is True
    assert write.annotations.idempotentHint is None


def test_help_is_first_in_live_tools_list() -> None:
    tools = _list_tool_sequence(build_mcp_server())
    assert tools[0].name == "help"


def test_help_is_first_and_writes_hidden_in_read_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNOW_KIT_ENABLE_WRITE", "1")
    default_tools = _list_tool_sequence(build_mcp_server())
    read_only_tools = _list_tool_sequence(build_mcp_server(read_only=True))
    assert default_tools[0].name == "help"
    assert read_only_tools[0].name == "help"
    assert "query_execute_write" in {tool.name for tool in default_tools}
    assert "query_execute_write" not in {tool.name for tool in read_only_tools}


def test_live_descriptions_expose_every_approved_alias_and_keyword() -> None:
    tools = _list_tools(build_mcp_server())
    for spec in all_specs():
        if spec.name == "query.execute_write":
            continue
        description = tools[spec.name.replace(".", "_")].description
        assert "Use this for:" in description
        for cue in discovery_cues(spec):
            assert cue in description


def test_enabled_write_description_exposes_approved_cues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNOW_KIT_ENABLE_WRITE", "1")
    description = _list_tools(build_mcp_server())["query_execute_write"].description
    write_spec = next(spec for spec in all_specs() if spec.name == "query.execute_write")
    assert all(cue in description for cue in discovery_cues(write_spec))


def test_mcp_help_does_not_initialize_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("MCP help crossed the metadata-only boundary")

    monkeypatch.setattr("snow_kit.core.config.SnowKitConfig.from_env", forbidden)
    monkeypatch.setattr("snow_kit.context.source.build_context_source", forbidden)
    for spec in all_specs():
        monkeypatch.setattr(spec, "fn", forbidden)
    server = build_mcp_server()
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        return await handler(
            CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(
                    name="help",
                    arguments={"intent": "search analytics context"},
                ),
            )
        )

    root = _root(asyncio.run(_run()))
    assert root.isError is False
    assert root.structuredContent["recommended_first_operation"] == "context.search"


def test_success_emits_validated_structured_content_and_json_fallback(
    monkeypatch: pytest.MonkeyPatch,
    fake_session: Any,
) -> None:
    monkeypatch.setattr(
        "snow_kit.services.query.core.default_session",
        lambda: fake_session,
    )
    server = build_mcp_server()
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        return await handler(
            CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(
                    name="query_execute",
                    arguments={"query": "SELECT 1", "max_rows": 1},
                ),
            )
        )

    root = _root(asyncio.run(_run()))

    assert root.isError is False
    assert root.structuredContent is not None
    assert root.structuredContent["data"]["rows"] == [{"ONE": 1}]
    assert json.loads(root.content[0].text) == root.structuredContent


def test_invalid_input_uses_snow_kit_error_envelope() -> None:
    server = build_mcp_server()
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        return await handler(
            CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(
                    name="query_execute",
                    arguments={"query": "SELECT 1", "max_rows": 0},
                ),
            )
        )

    root = _root(asyncio.run(_run()))
    payload = json.loads(root.content[0].text)

    assert root.isError is True
    assert root.structuredContent is None
    assert payload["error"] == "Validation"
    assert payload["op"] == "query.execute"


def test_real_client_session_over_stdio_lists_tools_and_reads_resources(
    tmp_path: Path,
) -> None:
    child_env = dict(os.environ)
    child_env[CONFIG_PATH_ENV] = str(tmp_path / "missing-config.env")
    child_env.pop(WRITE_FLAG, None)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "snow_kit.mcp", "--read-only"],
        env=child_env,
    )

    async def _run() -> tuple[Any, Any, Any, Any, Any]:
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                resources = await session.list_resources()
                status = await session.read_resource(SOURCE_STATUS_URI)
                help_result = await session.call_tool(
                    "help",
                    {
                        "intent": (
                            "Show a stacked bar chart of GMV by segment for the last month"
                        ),
                        "limit": 3,
                    },
                )
                return initialized, tools, resources, status, help_result

    initialized, tools, resources, status, help_result = asyncio.run(_run())

    assert initialized.serverInfo.name == "snow-kit"
    assert initialized.serverInfo.version == __version__
    assert "deterministic server-side" in (initialized.instructions or "")
    assert tools.tools[0].name == "help"
    tool_map = {tool.name: tool for tool in tools.tools}
    tool_names = set(tool_map)
    assert {"help", "context_search", "query_execute"} <= tool_names
    assert "query_execute_write" not in tool_names
    assert "performs no Snowflake query" in tool_map["help"].description
    assert "search analytics context" in tool_map["context_search"].description
    resource_uris = [str(resource.uri) for resource in resources.resources]
    assert SOURCE_STATUS_URI in resource_uris
    payload = json.loads(status.contents[0].text)
    assert payload["state"] == "context_unavailable"
    assert payload["source_count"] == 0
    assert help_result.isError is False
    assert help_result.structuredContent["status"] == "workflow"
    assert (
        help_result.structuredContent["recommended_first_operation"]
        == "context.search"
    )
    assert (
        json.loads(help_result.content[0].text)
        == help_result.structuredContent
    )
