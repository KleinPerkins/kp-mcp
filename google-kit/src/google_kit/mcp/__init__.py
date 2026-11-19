"""google-kit MCP server adapter — thin generic wrapper over the registry.

Exposes every registered OpSpec as an MCP tool. Input schema is derived from
the pydantic input_model; description from the first line of the core fn
docstring.  Adding an OpSpec automatically adds an MCP tool (R2).

Entry points:
  google-kit mcp           — start via CLI (preferred; uses Keychain auth)
  python -m google_kit.mcp — direct module invocation

The ``service=`` injection seam on every core function is preserved — tests
pass ``_service_factory`` to bypass Keychain auth.
"""
from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any, Callable

import google_kit  # noqa: F401 — triggers service auto-registration
from pydantic import ValidationError as PydanticValidationError

from google_kit.core.errors import GoogleKitError, Validation
from google_kit.core.flags import ENABLE_WRITES_FLAG, ensure_enabled
from google_kit.core.normalize import stable_json
from google_kit.core.run_id import new_run_id, reset_run_id, set_run_id
from google_kit.registry import all_specs, get
from kp_mcp_bootstrap.docgen import mcp_tool_name

# Synthetic meta-tool name (E6 intent resolver). Reserved: no OpSpec may sanitize
# to it (the build-time guard in ``_build_tool_map`` enforces this).
_HELP_TOOL_NAME = "help"
_MCP_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _tool_name(spec: Any) -> str:
    """MCP-valid tool name for an OpSpec.

    Thin wrapper over the shared ``mcp_tool_name`` sanitizer so the server and
    docgen emit identical names (e.g. ``gmail.manage_labels`` → ``gmail_manage_labels``).
    """
    return mcp_tool_name(spec.name)


def _build_tool_map(specs: list[Any]) -> dict[str, Any]:
    """Build the sanitized-tool-name → OpSpec map, guarding injectivity (R3).

    MCP tool names must match ``^[a-zA-Z0-9_]+$``, so each dotted op name is
    sanitized via ``_tool_name``. Op segments already contain underscores, so the
    forward map is the only safe way to round-trip a call back to its OpSpec —
    a naive ``name.replace("_", ".")`` is wrong (``gmail_manage_labels`` would
    decode to the non-existent ``gmail.manage.labels``).

    Raises ``ValueError`` at build time if two distinct op names sanitize to the
    same tool name (so a future op can never silently shadow another) or if an op
    collides with the reserved ``help`` meta-tool.
    """
    mapping: dict[str, Any] = {}
    for spec in specs:
        tname = _tool_name(spec)
        if not _MCP_TOOL_NAME_RE.fullmatch(tname):
            raise ValueError(
                f"OpSpec {spec.name!r} sanitizes to invalid MCP tool name {tname!r}; "
                "tool names must match ^[A-Za-z0-9_]{1,64}$."
            )
        if tname == _HELP_TOOL_NAME:
            raise ValueError(
                f"OpSpec {spec.name!r} sanitizes to the reserved MCP tool name "
                f"{_HELP_TOOL_NAME!r}; rename the op."
            )
        existing = mapping.get(tname)
        if existing is not None:
            raise ValueError(
                f"MCP tool-name collision: {existing.name!r} and {spec.name!r} "
                f"both sanitize to {tname!r}."
            )
        mapping[tname] = spec
    return mapping


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


def _first_line(doc: str | None) -> str:
    if not doc:
        return ""
    return doc.strip().splitlines()[0]


def _describe(spec: Any) -> str:
    """Tool description; appends an authorization note for ops that require it.

    Every op that requires authorization (``OpSpec.flag`` set — i.e. every
    ``write`` / ``destructive`` op) advertises that it is off until granted for
    the active profile, naming both the per-profile grant command and the env
    override that also satisfies the gate. Read / admin ops carry no note.
    """
    base = _first_line(spec.fn.__doc__)
    flag = getattr(spec, "flag", None)
    if flag:
        if flag.endswith("_WRITE"):
            note = (
                f" [write — requires authorization per profile: "
                f"`google-kit auth grant {spec.name}`, or set {flag}=1 "
                f"(or {ENABLE_WRITES_FLAG}=1 for all service write ops)]"
            )
        else:
            note = (
                f" [requires authorization per profile: "
                f"`google-kit auth grant {spec.name}`, or set {flag}=1]"
            )
        return (base + note) if base else note.strip()
    return base


def _format_validation_error(spec: Any, exc: PydanticValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()) if part != "__root__")
        name = loc or "input"
        parts.append(f"{name}: {err.get('msg', 'invalid value')}")
    detail = "; ".join(parts) or "invalid input"
    return f"Invalid arguments for {spec.name}: {detail}"


_HELP_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "description": "Natural-language description of the task, e.g. 'send an email'.",
        },
        "limit": {
            "type": "integer",
            "description": "Max matches to return (default 5).",
            "default": 5,
        },
    },
    "required": ["intent"],
}


def _resolve_help(arguments: dict[str, Any]) -> str:
    """Resolve the synthetic ``help`` tool: intent → ranked ops (stable JSON)."""
    from google_kit.core.manifest import resolve_intent

    intent = str(arguments.get("intent", "")).strip()
    limit = int(arguments.get("limit", 5) or 5)
    matches = resolve_intent(intent, limit=limit)
    payload = {
        "intent": intent,
        "matches": [
            {
                "op": m.op,
                "summary": _first_line(get(m.op).fn.__doc__),
                "score": m.score,
                "matched": list(m.matched),
            }
            for m in matches
        ],
    }
    return stable_json(payload)


def _default_service_factory(op_name: str, *, profile: str | None = None) -> Any:
    """Default factory: build real service from macOS Keychain."""
    from google_kit.core.auth import build_service_for_op

    return build_service_for_op(op_name, profile=profile)


def _service_kwargs(spec: Any, factory: Callable[..., Any]) -> dict[str, Any]:
    """Build the service kwargs to splat into a core fn (engine injection seam).

    Mirror of the CLI seam so the two surfaces stay at parity: recipe ops get a
    ``service`` resolver callable; multi-service ops (``<prefix>_service`` params)
    get one built resource per prefix; 1:1 ops get a single built resource.
    """
    if spec.name.startswith("recipes."):
        def _resolver(api_prefix: str) -> Any:
            return factory(f"{api_prefix}._recipe")

        return {"service": _resolver}

    kwargs: dict[str, Any] = {}
    for pname in inspect.signature(spec.fn).parameters:
        if pname == "service":
            kwargs["service"] = factory(spec.name)
        elif pname.endswith("_service"):
            prefix = pname[: -len("_service")]
            kwargs[pname] = factory(f"{prefix}._svc")
    return kwargs


def _invoke_tool_sync(
    spec: Any,
    arguments: dict[str, Any],
    factory: Callable[..., Any],
) -> str:
    """Validate, gate, and execute one tool call; return the JSON text payload.

    This runs the SYNCHRONOUS core function and all of its blocking work —
    Keychain ``security`` subprocess calls, googleapiclient network I/O, retry
    back-off ``sleep``s, and the audit-log file write. The MCP ``call_tool``
    handler offloads it to a worker thread (``asyncio.to_thread``) so the single
    asyncio event loop is never blocked: with the SDK dispatching every request
    as a concurrent task on one loop, a blocking call here would otherwise
    starve every other chat sharing this stdio server (and even the protocol
    pings) until they time out — the reported "two chats collided and one lost
    connectivity" failure.

    The ``run_id`` contextvar is set and reset inside this function so each call
    is isolated within its own worker thread. Errors are converted to the same
    MCP payloads the handler returned before, so behavior is unchanged.
    """
    token = set_run_id(new_run_id())
    try:
        _reject_unknown_arguments(spec, arguments or {})
        from google_kit.core.personal_runtime import operation
        with operation(spec):
            ensure_enabled(spec)
            inp = spec.input_model.model_validate(arguments or {})
            result = spec.fn(inp, **_service_kwargs(spec, factory))
            return stable_json(result.model_dump())
    except GoogleKitError as exc:
        return stable_json(exc.to_mcp_payload())
    except PydanticValidationError as exc:
        payload = Validation(
            _format_validation_error(spec, exc),
            op=spec.name,
        ).to_mcp_payload()
        return stable_json(payload)
    finally:
        reset_run_id(token)


def build_mcp_server(
    *,
    _service_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build and return a configured MCP Server instance.

    Args:
        _service_factory: Override auth builder for tests.

    Returns:
        Configured ``mcp.server.Server`` with list_tools and call_tool handlers.
    """
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    factory = _service_factory or _default_service_factory
    server = Server("google-kit")

    # Build the forward/reverse mapping ONCE so list_tools and call_tool stay in
    # lockstep: every advertised name resolves back to exactly one OpSpec, and a
    # collision (or a clash with the reserved `help` tool) fails fast at build time.
    tool_map = _build_tool_map(all_specs())

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        tools = [
            Tool(
                name=_HELP_TOOL_NAME,
                description=(
                    "Resolve a natural-language intent (e.g. 'send an email') to the "
                    "google-kit operations that satisfy it, ranked best-first."
                ),
                inputSchema=_HELP_INPUT_SCHEMA,
            )
        ]
        for tool_name in sorted(tool_map):
            spec = tool_map[tool_name]
            tools.append(
                Tool(
                    name=tool_name,
                    description=_describe(spec),
                    inputSchema=spec.input_model.model_json_schema(),
                )
            )
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == _HELP_TOOL_NAME:
            return [TextContent(type="text", text=_resolve_help(arguments))]
        spec = tool_map.get(name)
        if spec is None:
            raise KeyError(f"Unknown MCP tool: {name!r}")
        # Offload the blocking core fn to a worker thread so a slow call in one
        # chat never blocks the shared event loop (and thus every other chat
        # using this stdio server). The SDK dispatches each request as its own
        # task on a single loop, so a synchronous network/Keychain call awaited
        # inline would serialize the chats and time the others out. See
        # _invoke_tool_sync.
        text = await asyncio.to_thread(_invoke_tool_sync, spec, arguments or {}, factory)
        return [TextContent(type="text", text=text)]

    return server


async def run_server(
    *,
    _service_factory: Callable[..., Any] | None = None,
) -> None:
    """Run the google-kit MCP stdio server until the transport closes.

    Args:
        _service_factory: Override auth builder for tests.
    """
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(_service_factory=_service_factory)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Console-script entry point: start the MCP stdio server."""
    asyncio.run(run_server())
