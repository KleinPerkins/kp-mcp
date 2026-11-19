"""Cursor MCP registrar."""

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


class CursorRegistrar(BaseRegistrar):
    """Field-aware registrar for Cursor's mcp.json."""

    _KEY = "mcpServers"
    SURFACE = "cursor"
    FIXTURE_BUILD = "cursor-fixture-v1"
    FIXTURE_CONFIG_NAME = "mcp.json"
    MAPPING_VERSION = "cursor-mcp-json/v1"
    MAPPING_SPEC = {
        "stdio": ("command", "args", "env/*"),
        "streamable-http": ("url", "headers/*"),
    }
    SUPPORTED_READ_BUILDS = frozenset({"cursor-source-v1", FIXTURE_BUILD})

    def _empty_data(self) -> dict[str, Any]:
        return {self._KEY: {}}

    def _parse_bytes(self, data: bytes) -> dict[str, Any]:
        parsed = native_json_loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("Cursor config root must be a map")
        servers = parsed.setdefault(self._KEY, {})
        if not isinstance(servers, dict):
            raise ValueError("Cursor mcpServers must be a map")
        return parsed

    def _serialize_data(self, data: Any) -> bytes:
        return native_json_dumps(data)

    def _get_entry(
        self, data: dict[str, Any], native_name: str | None = None
    ) -> Mapping[str, Any] | None:
        entry = data.get(self._KEY, {}).get(native_name or self.SERVER_NAME)
        if entry is not None and not isinstance(entry, Mapping):
            raise ValueError("Cursor server entry must be a map")
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
        transport = definition.transport
        source: dict[str, Any] = {}
        auth: dict[str, Any] = {}
        binding = context.auth_binding
        if isinstance(transport, StdioTransport):
            if binding and (
                binding.kind is not AuthKind.NONE
                or binding.target_origin_digest
                != digest_value(
                    {"transport": "stdio", "command": transport.command}
                )
            ):
                raise RegistrarError(ReasonCode.AUTH_BINDING_CONFLICT)
            source["/command"] = transport.command
            source["/args"] = list(transport.args)
            for key, value in transport.env.items():
                source[f"/env/{pointer_escape(key)}"] = value
            incompatible = frozenset({"/url", "/type", "/headers/*"})
        elif isinstance(transport, StreamableHTTPTransport):
            if binding is None or binding.target_origin_digest != digest_value(
                {"transport": "streamable-http", "url": transport.url}
            ):
                raise RegistrarError(ReasonCode.AUTH_BINDING_CONFLICT)
            source["/url"] = transport.url
            incompatible = frozenset({"/command", "/args", "/env/*", "/type"})
        else:
            raise RegistrarError(ReasonCode.UNSUPPORTED_TRANSPORT)
        if binding and binding.kind is AuthKind.ENVIRONMENT_REFERENCE:
            if not isinstance(transport, StreamableHTTPTransport):
                raise RegistrarError(ReasonCode.AUTH_BINDING_CONFLICT)
            allowed = set(binding.allowed_native_fields)
            expected = {"/headers/Authorization"}
            if allowed != expected or not binding.environment_variable:
                raise RegistrarError(ReasonCode.AUTH_BINDING_CONFLICT)
            auth["/headers/Authorization"] = f"${{env:{binding.environment_variable}}}"
        return source, auth, incompatible
