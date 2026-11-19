"""Claude Code MCP registrar."""

from typing import Any, Mapping

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError

from .base import BaseRegistrar
from .native_json import loads as native_json_loads, dumps as native_json_dumps
from .contracts import (
    AuthKind,
    RegistrationContext,
    RegistrationDefinition,
    StdioTransport,
    StreamableHTTPTransport,
    digest_value,
    pointer_escape,
)


class ClaudeRegistrar(BaseRegistrar):
    """Field-aware registrar for Claude Code's user-scope JSON config."""

    _KEY = "mcpServers"
    SURFACE = "claude"
    FIXTURE_BUILD = "claude-fixture-v1"
    FIXTURE_CONFIG_NAME = ".claude.json"
    MAPPING_VERSION = "claude-user-json/v1"
    MAPPING_SPEC = {
        "stdio": ("type=stdio", "command", "args", "env/*"),
        "streamable-http": "unsupported",
    }
    SUPPORTED_READ_BUILDS = frozenset({"claude-source-v1", FIXTURE_BUILD})

    def _empty_data(self) -> dict[str, Any]:
        return {self._KEY: {}}

    def _parse_bytes(self, data: bytes) -> dict[str, Any]:
        parsed = native_json_loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("Claude config root must be a map")
        servers = parsed.setdefault(self._KEY, {})
        if not isinstance(servers, dict):
            raise ValueError("Claude mcpServers must be a map")
        return parsed

    def _serialize_data(self, data: Any) -> bytes:
        return native_json_dumps(data)

    def _get_entry(
        self, data: dict[str, Any], native_name: str | None = None
    ) -> Mapping[str, Any] | None:
        entry = data.get(self._KEY, {}).get(native_name or self.SERVER_NAME)
        if entry is not None and not isinstance(entry, Mapping):
            raise ValueError("Claude server entry must be a map")
        return entry

    def _set_entry(
        self,
        data: dict[str, Any],
        entry: Mapping[str, Any],
        native_name: str | None = None,
    ) -> dict[str, Any]:
        data.setdefault(self._KEY, {})[native_name or self.SERVER_NAME] = dict(entry)
        return data

    def _remove_entry(
        self, data: dict[str, Any], native_name: str | None = None
    ) -> dict[str, Any]:
        data.setdefault(self._KEY, {}).pop(native_name or self.SERVER_NAME, None)
        return data

    def _native_projection(
        self,
        definition: RegistrationDefinition,
        context: RegistrationContext,
    ) -> tuple[dict[str, Any], dict[str, Any], frozenset[str]]:
        if isinstance(definition.transport, StreamableHTTPTransport):
            raise RegistrarError(ReasonCode.UNSUPPORTED_TRANSPORT)
        if not isinstance(definition.transport, StdioTransport):
            raise RegistrarError(ReasonCode.UNSUPPORTED_TRANSPORT)
        transport = definition.transport
        if context.auth_binding and (
            context.auth_binding.kind is not AuthKind.NONE
            or context.auth_binding.target_origin_digest
            != digest_value(
                {"transport": "stdio", "command": transport.command}
            )
        ):
            raise RegistrarError(ReasonCode.AUTH_BINDING_CONFLICT)
        source: dict[str, Any] = {
            "/type": "stdio",
            "/command": transport.command,
            "/args": list(transport.args),
        }
        for key, value in transport.env.items():
            source[f"/env/{pointer_escape(key)}"] = value
        return source, {}, frozenset({"/url", "/headers/*"})
