"""Codex MCP registrar with syntax-preserving TOML edits."""

from collections.abc import Mapping, MutableMapping
from typing import Any

import tomlkit
from tomlkit.items import AoT

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError

from .base import BaseRegistrar
from .contracts import (
    AuthKind,
    RegistrationContext,
    RegistrationDefinition,
    StdioTransport,
    StreamableHTTPTransport,
    digest_value,
    pointer_escape,
)


class CodexRegistrar(BaseRegistrar):
    """Field-aware registrar for Codex config.toml."""

    _SECTION = "mcp_servers"
    SURFACE = "codex"
    FIXTURE_BUILD = "codex-fixture-v1"
    FIXTURE_CONFIG_NAME = "config.toml"
    MAPPING_VERSION = "codex-config-toml/v1"
    MAPPING_SPEC = {
        "stdio": ("command", "args", "env/*"),
        "streamable-http": (
            "url",
            "bearer_token_env_var",
            "env_http_headers/*",
        ),
    }
    SUPPORTED_READ_BUILDS = frozenset({"codex-source-v1", FIXTURE_BUILD})

    def _empty_data(self) -> Any:
        document = tomlkit.document()
        document.add(self._SECTION, tomlkit.table())
        return document

    def _parse_bytes(self, data: bytes) -> Any:
        text = data.decode("utf-8")
        document = tomlkit.parse(text)
        if tomlkit.dumps(document) != text:
            raise RegistrarError(ReasonCode.UNSUPPORTED_FIELD)
        section = document.get(self._SECTION)
        if section is None:
            document.add(self._SECTION, tomlkit.table())
        elif not isinstance(section, MutableMapping) or isinstance(section, AoT):
            raise ValueError("Codex mcp_servers must be a table")
        return document

    def _serialize_data(self, data: Any) -> bytes:
        return tomlkit.dumps(data).encode("utf-8")

    def _get_entry(
        self, data: Any, native_name: str | None = None
    ) -> Mapping[str, Any] | None:
        section = data.get(self._SECTION, {})
        entry = section.get(native_name or self.SERVER_NAME)
        if entry is not None and (
            not isinstance(entry, Mapping) or isinstance(entry, AoT)
        ):
            raise ValueError("Codex server entry must be a table")
        return entry

    def _sync_mapping(
        self, current: MutableMapping[str, Any], desired: Mapping[str, Any]
    ) -> None:
        for key in tuple(current):
            if key not in desired:
                del current[key]
        for key, value in desired.items():
            existing = current.get(key)
            if isinstance(existing, MutableMapping) and isinstance(value, Mapping):
                self._sync_mapping(existing, value)
            elif existing != value:
                current[key] = value

    def _set_entry(
        self,
        data: Any,
        entry: Mapping[str, Any],
        native_name: str | None = None,
    ) -> Any:
        section = data.get(self._SECTION)
        if section is None:
            section = tomlkit.table()
            data.add(self._SECTION, section)
        name = native_name or self.SERVER_NAME
        current = section.get(name)
        if not isinstance(current, MutableMapping) or isinstance(current, AoT):
            current = tomlkit.table()
            section[name] = current
        self._sync_mapping(current, entry)
        return data

    def _remove_entry(self, data: Any, native_name: str | None = None) -> Any:
        data.get(self._SECTION, {}).pop(native_name or self.SERVER_NAME, None)
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
            incompatible = frozenset(
                {"/url", "/bearer_token_env_var", "/env_http_headers/*"}
            )
        elif isinstance(transport, StreamableHTTPTransport):
            if binding is None or binding.target_origin_digest != digest_value(
                {"transport": "streamable-http", "url": transport.url}
            ):
                raise RegistrarError(ReasonCode.AUTH_BINDING_CONFLICT)
            source["/url"] = transport.url
            incompatible = frozenset({"/command", "/args", "/env/*"})
        else:
            raise RegistrarError(ReasonCode.UNSUPPORTED_TRANSPORT)
        if binding and binding.kind is AuthKind.ENVIRONMENT_REFERENCE:
            if not isinstance(transport, StreamableHTTPTransport):
                raise RegistrarError(ReasonCode.AUTH_BINDING_CONFLICT)
            allowed = set(binding.allowed_native_fields)
            variable = binding.environment_variable
            if allowed == {"/bearer_token_env_var"} and variable:
                auth["/bearer_token_env_var"] = variable
            elif variable and all(
                path.startswith("/env_http_headers/") for path in allowed
            ):
                for path in allowed:
                    auth[path] = variable
            else:
                raise RegistrarError(ReasonCode.AUTH_BINDING_CONFLICT)
        return source, auth, incompatible
