"""Stable registrar import surface and legacy ServerEntry value object."""

from __future__ import annotations

from typing import Any

from .engine import RegistrarV1Base as BaseRegistrar


class ServerEntry:
    """Minimal stdio server entry retained for existing kit constructors."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = args or ["mcp"]
        self.env = env or {}

    def as_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"command": self.command, "args": self.args}
        if self.env:
            entry["env"] = self.env
        return entry


__all__ = ["BaseRegistrar", "ServerEntry"]
