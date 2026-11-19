"""snow-kit MCP stdio server with read-default tool exposure."""
from __future__ import annotations

import asyncio
import os
import re
import sys
from typing import TYPE_CHECKING, Any, Callable

import snow_kit  # noqa: F401 — triggers service auto-registration
from pydantic import ValidationError as PydanticValidationError

from kp_mcp_bootstrap.docgen import mcp_tool_name
from snow_kit.core.config import SnowKitConfig
from snow_kit.core.errors import SnowKitError, Timeout, Validation, classify_connector
from snow_kit.core.flags import ensure_enabled
from snow_kit.core.intents import HelpInput, HelpOutput, resolve_help, visible_specs
from snow_kit.core.normalize import stable_json
from snow_kit.mcp.metadata import (
    HELP_TOOL_DESCRIPTION,
    SERVER_INSTRUCTIONS,
    installed_version,
    tool_annotations,
    tool_description,
)
from snow_kit.mcp.resources import register_resource_handlers
from snow_kit.registry import all_specs

if TYPE_CHECKING:
    from mcp.types import CallToolResult

_MCP_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_HELP_TOOL_NAME = "help"


def _build_tool_map(specs: list[Any]) -> dict[str, Any]:
    """Map sanitized MCP tool name → OpSpec, guarding injectivity.

    MCP tool names must match ``^[a-zA-Z0-9_]+$``, so dotted op names are
    sanitized via ``mcp_tool_name``. Because op segments may contain underscores,
    this forward map is the only safe way to round-trip a call back to its
    OpSpec. Raises if two distinct ops sanitize to the same tool name or collide
    with the reserved help meta-tool.
    """
    mapping: dict[str, Any] = {}
    for spec in specs:
        tool_name = mcp_tool_name(spec.name)
        if not _MCP_TOOL_NAME_RE.fullmatch(tool_name):
            raise ValueError(f"OpSpec {spec.name!r} sanitizes to invalid MCP tool name {tool_name!r}.")
        if tool_name == _HELP_TOOL_NAME:
            raise ValueError(
                f"OpSpec {spec.name!r} sanitizes to reserved MCP tool name "
                f"{_HELP_TOOL_NAME!r}."
            )
        existing = mapping.get(tool_name)
        if existing is not None:
            raise ValueError(
                f"MCP tool-name collision: {existing.name!r} and {spec.name!r} "
                f"both sanitize to {tool_name!r}."
            )
        mapping[tool_name] = spec
    return mapping


def _visible_specs(specs: list[Any], *, read_only: bool = False) -> list[Any]:
    """Compatibility wrapper around the shared Snow visibility policy."""
    return visible_specs(specs, read_only=read_only)


def _format_validation_error(spec: Any, exc: PydanticValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()) if part != "__root__")
        parts.append(f"{loc or 'input'}: {err.get('msg', 'invalid value')}")
    return f"Invalid arguments for {spec.name}: {'; '.join(parts)}"


def _reject_unknown_arguments(spec: Any, arguments: dict[str, Any]) -> None:
    """Reject MCP arguments that pydantic would otherwise ignore by default."""
    allowed: set[str] = set(spec.input_model.model_fields)
    for field in spec.input_model.model_fields.values():
        alias = getattr(field, "alias", None)
        if alias:
            allowed.add(alias)
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        allowed_fields = ", ".join(sorted(allowed)) or "(none)"
        raise Validation(
            f"Unknown argument(s) for {spec.name}: {', '.join(unknown)}. "
            f"Allowed arguments: {allowed_fields}.",
            op=spec.name,
        )


def _error_result(exc: SnowKitError) -> CallToolResult:
    """Return a protocol-level failed tool result with the existing JSON payload."""
    from mcp.types import CallToolResult, TextContent

    text = stable_json(exc.to_mcp_payload())
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        isError=True,
    )


def _invoke_tool_sync(
    spec: Any,
    arguments: dict[str, Any],
    *,
    read_only: bool = False,
) -> dict[str, Any] | CallToolResult:
    """Validate, gate, and execute one synchronous core op in a worker thread."""
    try:
        _reject_unknown_arguments(spec, arguments or {})
        if read_only and spec.posture in {"write", "destructive"}:
            from snow_kit.core.flags import FlagDisabledError

            raise FlagDisabledError(
                f"{spec.name} is unavailable in fail-closed read-only MCP mode.",
                op=spec.name,
            )
        ensure_enabled(spec)
        inp = spec.input_model.model_validate(arguments or {})
        result = spec.fn(inp)
        return result.model_dump(mode="json")
    except SnowKitError as exc:
        return _error_result(exc)
    except PydanticValidationError as exc:
        return _error_result(
            Validation(
                _format_validation_error(spec, exc),
                op=spec.name,
            )
        )
    except Exception as exc:  # noqa: BLE001 - classify guard/connector failures for MCP transport.
        return _error_result(classify_connector(exc, op=spec.name))


def build_mcp_server(
    *,
    read_only: bool = False,
    _backend_factory: Callable[[str], Any] | None = None,
) -> Any:
    """Build the MCP Server. ``_backend_factory`` is accepted for legacy tests."""
    del _backend_factory
    from mcp.server import Server
    from mcp.types import Tool, ToolAnnotations

    server = Server(
        "snow-kit",
        version=installed_version(),
        instructions=SERVER_INSTRUCTIONS,
    )

    # Build the sanitized-name → OpSpec map ONCE so list_tools and call_tool stay
    # in lockstep and a name collision fails fast at build time.
    tool_map = _build_tool_map(all_specs())

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        visible_map = _build_tool_map(_visible_specs(all_specs(), read_only=read_only))
        tools = [
            Tool(
                name=_HELP_TOOL_NAME,
                description=HELP_TOOL_DESCRIPTION,
                inputSchema=HelpInput.model_json_schema(),
                outputSchema=HelpOutput.model_json_schema(),
                annotations=ToolAnnotations(
                    title="Snow-kit Help",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
        ]
        tools.extend(
            Tool(
                name=tool_name,
                description=tool_description(visible_map[tool_name]),
                inputSchema=visible_map[tool_name].input_model.model_json_schema(),
                outputSchema=visible_map[tool_name].output_model.model_json_schema(),
                annotations=tool_annotations(visible_map[tool_name]),
            )
            for tool_name in sorted(visible_map)
        )
        return tools

    @server.call_tool(validate_input=False)
    async def _call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | CallToolResult:
        if name == _HELP_TOOL_NAME:
            try:
                help_input = HelpInput.model_validate(arguments or {})
                return resolve_help(
                    help_input.intent,
                    limit=help_input.limit,
                    specs=_visible_specs(all_specs(), read_only=read_only),
                ).model_dump(mode="json")
            except PydanticValidationError as exc:
                detail = "; ".join(
                    f"{'.'.join(str(part) for part in error.get('loc', ())) or 'input'}: "
                    f"{error.get('msg', 'invalid value')}"
                    for error in exc.errors()
                )
                return _error_result(
                    Validation(
                        f"Invalid arguments for help: {detail}",
                        op="help",
                    )
                )
        spec = tool_map.get(name)
        if spec is None:
            return _error_result(
                Validation(
                    f"Unknown MCP tool: {name!r}. Call tools/list for supported names.",
                    op=name,
                )
            )
        try:
            timeout = SnowKitConfig.from_env().tool_timeout_seconds
        except Exception as exc:  # noqa: BLE001 - config failures use the normal MCP taxonomy.
            return _error_result(classify_connector(exc, op=spec.name))
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    _invoke_tool_sync,
                    spec,
                    arguments or {},
                    read_only=read_only,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return _error_result(
                Timeout(
                    f"Tool timed out after {timeout}s.",
                    op=spec.name,
                )
            )
        return result

    register_resource_handlers(server)

    return server


async def run_server(
    *,
    read_only: bool = False,
    _backend_factory: Callable[[str], Any] | None = None,
) -> None:
    """Run the MCP stdio server until the transport closes."""
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(read_only=read_only, _backend_factory=_backend_factory)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: list[str] | None = None) -> None:
    """Console entry point: start the MCP stdio server."""
    args = list(sys.argv[1:] if argv is None else argv)
    read_only = False
    if args == ["--read-only"]:
        read_only = True
        os.environ.pop("SNOW_KIT_ENABLE_WRITE", None)
    elif args:
        raise SystemExit("usage: snow-kit mcp [--read-only]")
    asyncio.run(run_server(read_only=read_only))
