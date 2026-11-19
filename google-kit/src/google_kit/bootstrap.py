"""Platform registrar wiring for google-kit.

Registers the google-kit MCP server with Cursor, Codex, and Claude Code
platform configs.  All paths are caller-supplied for testability — tests use
``tmp_path`` exclusively; production callers pass the real config paths.

Security: configs contain ONLY the server launch command + non-secret env.
No tokens, credentials, or secrets are written (R15/B6).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Mapping

from kp_mcp_bootstrap.registrars import ClaudeRegistrar, CodexRegistrar, CursorRegistrar
from kp_mcp_bootstrap.registrars.base import ServerEntry

from kp_mcp_bootstrap.registrars import Approval, PreparedOperation, RegistrationContext, RegistrationDefinition, Result, RegistrarError, ReasonCode
from kp_mcp_bootstrap.registrars.consumers import kit_definition, registration_batch

SERVER_NAME = "google-kit"


def registrars(*, maintenance_validator=None):
    """Return this kit's adapters for explicit owner context construction."""
    return {"cursor": CursorRegistrar(maintenance_validator=maintenance_validator), "codex": CodexRegistrar(maintenance_validator=maintenance_validator), "claude": ClaudeRegistrar(maintenance_validator=maintenance_validator)}


def registration_definition(source_revision: str, binary_path: str | None = None, *, env=None) -> RegistrationDefinition:
    """Build the stable kit identity and complete owned launch projection."""
    return kit_definition(SERVER_NAME, source_revision, google_kit_server_entry(binary_path, env=env))


def _default_binary() -> str:
    """Resolve the absolute path to the google-kit script in the active venv."""
    import shutil

    found = shutil.which("google-kit")
    if found:
        return found
    scripts = Path(sys.executable).parent
    candidate = scripts / "google-kit"
    return str(candidate)


def default_user_config_dir() -> Path:
    """Return the explicit user-level google-kit config dir for bootstrap."""
    configured = os.environ.get("GOOGLE_KIT_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "google-kit"
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
    return xdg / "google-kit"


def google_kit_server_entry(
    binary_path: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> ServerEntry:
    """Build a ServerEntry for the google-kit MCP server.

    Args:
        binary_path: Absolute path to the google-kit binary.  Defaults to the
                     binary resolved from the active virtual environment.
        env: Only GOOGLE_KIT_CONFIG_DIR is source-owned. Account, auth and
             enablement choices remain host-owned.

    Returns:
        A ``ServerEntry`` with ``command=<binary>``, ``args=["mcp"]``.
    """
    if env:
        if set(env) - {"GOOGLE_KIT_CONFIG_DIR"}:
            raise RegistrarError(ReasonCode.UNSUPPORTED_FIELD)
        if not Path(env["GOOGLE_KIT_CONFIG_DIR"]).is_absolute():
            raise RegistrarError(ReasonCode.UNSUPPORTED_FIELD)
    cmd = binary_path or _default_binary()
    return ServerEntry(command=cmd, args=["mcp"], env=env or {})


def register_all(
    *, cursor_path: Path, codex_path: Path, claude_path: Path,
    binary_path: str | None = None, env: dict[str, str] | None = None,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
    maintenance_validator=None,
    dry_run: bool = False,
) -> dict[str, Result | str]:
    """Preflight every host and apply only explicitly supplied operations."""
    return registration_batch(
        SERVER_NAME, registrars(maintenance_validator=maintenance_validator),
        {"cursor": cursor_path, "codex": codex_path, "claude": claude_path},
        google_kit_server_entry(binary_path, env=env), contexts=contexts,
        prepared=prepared, approvals=approvals, dry_run=dry_run,
    )


def unregister_all(
    *, cursor_path: Path, codex_path: Path, claude_path: Path,
    binary_path: str | None = None, env: dict[str, str] | None = None,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
    maintenance_validator=None,
    dry_run: bool = False,
) -> dict[str, Result | str]:
    """Withdraw a fully owned entry through exact prepared operations."""
    return registration_batch(
        SERVER_NAME, registrars(maintenance_validator=maintenance_validator),
        {"cursor": cursor_path, "codex": codex_path, "claude": claude_path},
        google_kit_server_entry(binary_path, env=env), contexts=contexts,
        prepared=prepared, approvals=approvals, dry_run=dry_run, remove=True,
    )


def default_platform_paths() -> dict[str, Path]:
    """Return the real operator config paths for each platform.

    These are the production paths.  Tests MUST use tmp_path instead.
    """
    home = Path.home()
    return {
        "cursor": home / ".cursor" / "mcp.json",
        "codex": home / ".codex" / "config.toml",
        "claude": home / ".claude.json",
    }


def bootstrap(
    *, binary_path: str | None = None, env: dict[str, str] | None = None,
    dry_run: bool = False,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
    maintenance_validator=None,
) -> dict[str, Any]:
    """Register through explicit owner authority; profile repair is separate."""
    paths = default_platform_paths()
    server_env = {"GOOGLE_KIT_CONFIG_DIR": str(default_user_config_dir())}
    server_env.update(env or {})
    return register_all(
        cursor_path=paths["cursor"], codex_path=paths["codex"], claude_path=paths["claude"],
        binary_path=binary_path, env=server_env, dry_run=dry_run,
        contexts=contexts, prepared=prepared, approvals=approvals, maintenance_validator=maintenance_validator,
    )
