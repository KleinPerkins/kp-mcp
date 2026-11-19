"""widget-kit MCP stdio server — generic wrapper over the registry.

Exposes every registered OpSpec as an MCP tool. Input schema derives from the
pydantic ``input_model``; the description from the core fn docstring. Adding an
OpSpec automatically adds an MCP tool. The ``mcp`` import is lazy so the package
imports (and builds) without the optional runtime dependency installed.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

import widget_kit  # noqa: F401 — triggers service auto-registration
from widget_kit.core.normalize import stable_json
from widget_kit.registry import all_specs
from kp_mcp_bootstrap.docgen import mcp_tool_name


def _first_line(doc: str | None) -> str:
    return doc.strip().splitlines()[0] if doc else ""


def _build_tool_map(specs: list[Any]) -> dict[str, Any]:
    """Map sanitized MCP tool name → OpSpec, guarding injectivity.

    MCP tool names must match ``^[a-zA-Z0-9_]+$``, so dotted op names are
    sanitized via ``mcp_tool_name``. Because op segments may contain underscores,
    this forward map is the only safe way to round-trip a call back to its
    OpSpec. Raises if two distinct ops sanitize to the same tool name.
    """
    mapping: dict[str, Any] = {}
    for spec in specs:
        tool_name = mcp_tool_name(spec.name)
        existing = mapping.get(tool_name)
        if existing is not None:
            raise ValueError(
                f"MCP tool-name collision: {existing.name!r} and {spec.name!r} "
                f"both sanitize to {tool_name!r}."
            )
        mapping[tool_name] = spec
    return mapping


def build_mcp_server(*, _backend_factory: Callable[[str], Any] | None = None) -> Any:
    """Build the MCP Server. ``_backend_factory`` overrides auth for tests."""
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    server = Server("widget-kit")

    # Build the sanitized-name → OpSpec map ONCE so list_tools and call_tool stay
    # in lockstep and a name collision fails fast at build time.
    tool_map = _build_tool_map(all_specs())

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=tool_name,
                description=_first_line(tool_map[tool_name].fn.__doc__),
                inputSchema=tool_map[tool_name].input_model.model_json_schema(),
            )
            for tool_name in sorted(tool_map)
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        spec = tool_map.get(name)
        if spec is None:
            raise KeyError(f"Unknown MCP tool: {name!r}")
        inp = spec.input_model.model_validate(arguments)
        kwargs: dict[str, Any] = {}
        if _backend_factory is not None:
            kwargs["backend"] = _backend_factory(spec.name)
        result = spec.fn(inp, **kwargs)
        return [TextContent(type="text", text=stable_json(result.model_dump()))]

    return server


async def run_server(*, _backend_factory: Callable[[str], Any] | None = None) -> None:
    """Run the MCP stdio server until the transport closes."""
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(_backend_factory=_backend_factory)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Console entry point: start the MCP stdio server."""
    asyncio.run(run_server())
