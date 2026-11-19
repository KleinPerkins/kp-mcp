"""Registration, status, and doctor lifecycle for snow-kit."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from kp_mcp_bootstrap.registrars import ClaudeRegistrar, CodexRegistrar, CursorRegistrar
from kp_mcp_bootstrap.registrars.base import BaseRegistrar, ServerEntry
from kp_mcp_bootstrap.registrars import (
    Approval, PreparedOperation, RegistrationContext, RegistrationDefinition,
    Result, Outcome, ReasonCode, RegistrarError,
)
from kp_mcp_bootstrap.registrars.consumers import kit_definition, registration_batch

from snow_kit import __version__
from snow_kit.context import context_source_status, validate_default_context_governance
from snow_kit.context.source import default_context_pattern
from snow_kit.core.config import (
    CONFIG_PATH_ENV,
    CONTEXT_ALLOW_PATHS_KEY,
    CONTEXT_MODE_KEY,
    CONTEXT_REPO_KEY,
    CURRENT_PROFILE_VERSION,
    PROFILE_VERSION_KEY,
    WRITE_FLAG,
    ConfigError,
    SnowKitConfig,
    bootstrap_env,
    default_config_path,
    load_profile,
    profile_keys,
    repair_profile,
    resolve_snowflake_user,
    write_profile,
)
from snow_kit.core.errors import Auth, Permission
from snow_kit.core.normalize import stable_json
from snow_kit.registry import all_specs

SERVER_NAME = "snow-kit"


class _Cursor(CursorRegistrar):
    SERVER_NAME = "snow-kit"


class _Codex(CodexRegistrar):
    SERVER_NAME = "snow-kit"


class _Claude(ClaudeRegistrar):
    SERVER_NAME = "snow-kit"


_PLATFORMS: tuple[tuple[str, type[BaseRegistrar]], ...] = (
    ("cursor", _Cursor),
    ("codex", _Codex),
    ("claude", _Claude),
)


def _default_binary() -> str:
    """Resolve the absolute path to the snow-kit script in the active venv."""
    found = shutil.which("snow-kit")
    if found:
        return found
    return str(Path(sys.executable).parent / "snow-kit")


def server_entry(
    binary_path: str | None = None,
    *,
    env: dict[str, str] | None = None,
    config_path: Path | None = None,
) -> ServerEntry:
    """Build the fail-closed registration entry.

    Registrations contain only a stable command, ``mcp --read-only``, and the
    canonical profile pointer. Connection values never appear in client files.
    """
    server_env = bootstrap_env(config_path=config_path)
    if env:
        unsupported = set(env) - {CONFIG_PATH_ENV}
        if unsupported:
            raise RegistrarError(ReasonCode.UNSUPPORTED_FIELD)
        override = Path(env[CONFIG_PATH_ENV]).expanduser()
        if not override.is_absolute():
            raise RegistrarError(ReasonCode.UNSUPPORTED_FIELD)
        env = {CONFIG_PATH_ENV: str(override)}
        server_env.update(env)
    server_env.pop(WRITE_FLAG, None)
    return ServerEntry(
        command=binary_path or _default_binary(),
        args=["mcp", "--read-only"],
        env=server_env,
    )


def default_platform_paths() -> dict[str, Path]:
    """Return the real operator config paths. Tests MUST pass tmp_path instead."""
    home = Path.home()
    return {
        "cursor": home / ".cursor" / "mcp.json",
        "codex": home / ".codex" / "config.toml",
        "claude": home / ".claude.json",
    }


def _read_only_policy(current: dict, proposed: dict):
    """Reject overrides that could defeat the kit's reviewed read-only launch."""
    if WRITE_FLAG in (current.get("env") or {}):
        return ReasonCode.POLICY_CONFLICT
    if any(key in current for key in ("envFile", "env_file", "env_vars", "cwd")):
        return ReasonCode.POLICY_CONFLICT
    return None


def registrars(*, maintenance_validator=None):
    """Return adapters with the private Snow launch-invariant validator."""
    return {
        host: cls(policy_validator=_read_only_policy, policy_validator_id="snow/read-only/v1", maintenance_validator=maintenance_validator)
        for host, cls in _PLATFORMS
    }


def registration_definition(
    source_revision: str, binary_path: str | None = None, *,
    env: dict[str, str] | None = None, config_path: Path | None = None,
) -> RegistrationDefinition:
    """Build the stable kit identity and complete read-only launch projection."""
    return kit_definition(SERVER_NAME, source_revision, server_entry(binary_path, env=env, config_path=config_path))


def register_all(
    *, cursor_path: Path, codex_path: Path, claude_path: Path,
    binary_path: str | None = None, env: dict[str, str] | None = None,
    config_path: Path | None = None, dry_run: bool = False,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
    maintenance_validator=None,
    _validate_only: bool = False,
) -> dict[str, Result | str]:
    """Preflight all hosts, then apply exact prepared operations sequentially."""
    return registration_batch(
        SERVER_NAME, registrars(maintenance_validator=maintenance_validator),
        {"cursor": cursor_path, "codex": codex_path, "claude": claude_path},
        server_entry(binary_path, env=env, config_path=config_path),
        contexts=contexts, prepared=prepared, approvals=approvals, dry_run=dry_run,
        validate_only=_validate_only,
    )


def unregister_all(
    *, cursor_path: Path, codex_path: Path, claude_path: Path,
    binary_path: str | None = None, env: dict[str, str] | None = None,
    config_path: Path | None = None, dry_run: bool = False,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
    maintenance_validator=None,
) -> dict[str, Result | str]:
    """Withdraw only an entirely owned entry with exact operation approval."""
    return registration_batch(
        SERVER_NAME, registrars(maintenance_validator=maintenance_validator),
        {"cursor": cursor_path, "codex": codex_path, "claude": claude_path},
        server_entry(binary_path, env=env, config_path=config_path),
        contexts=contexts, prepared=prepared, approvals=approvals, dry_run=dry_run, remove=True,
    )


def bootstrap(
    *, binary_path: str | None = None, env: dict[str, str] | None = None,
    config_path: Path | None = None, dry_run: bool = False,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
    maintenance_validator=None,
    _validate_only: bool = False,
) -> dict[str, Any]:
    """Registration-only entrypoint; all owner authority is explicit."""
    paths = default_platform_paths()
    return register_all(
        cursor_path=paths["cursor"], codex_path=paths["codex"], claude_path=paths["claude"],
        binary_path=binary_path, env=env, config_path=config_path, dry_run=dry_run,
        contexts=contexts, prepared=prepared, approvals=approvals, maintenance_validator=maintenance_validator, _validate_only=_validate_only,
    )


def setup(
    *,
    binary_path: str | None = None,
    config_path: Path | None = None,
    profile_values: Mapping[str, str] | None = None,
    context_repo: Path | None = None,
    context_paths: tuple[str, ...] = (),
    context_mode: str | None = None,
    dry_run: bool = False,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
) -> dict[str, Any]:
    """Create/update the secure v0.1.1 profile, then register all clients."""
    path = (config_path or default_config_path()).expanduser()
    preflight = bootstrap(
        binary_path=binary_path, config_path=path, dry_run=dry_run,
        contexts=contexts, prepared=prepared, approvals=approvals, _validate_only=True,
    )
    updates = {
        key: value
        for key in profile_keys()
        if (value := os.environ.get(key))
    }
    updates.update(profile_values or {})
    updates[PROFILE_VERSION_KEY] = str(CURRENT_PROFILE_VERSION)
    if not updates.get("SNOW_KIT_USER"):
        try:
            user = resolve_snowflake_user(config_path=path)
        except ConfigError:
            user = None
        if user:
            updates["SNOW_KIT_USER"] = user
    proposed_default = False
    if context_repo is not None:
        root = context_repo.expanduser()
        if not root.is_absolute():
            raise ConfigError("setup --context-repo must be an absolute path")
        updates[CONTEXT_REPO_KEY] = str(root)
        if context_paths:
            updates[CONTEXT_ALLOW_PATHS_KEY] = json.dumps(
                list(context_paths),
                separators=(",", ":"),
            )
        elif validate_default_context_governance(root):
            updates[CONTEXT_ALLOW_PATHS_KEY] = json.dumps(
                [default_context_pattern()],
                separators=(",", ":"),
            )
            proposed_default = True
    elif context_paths:
        updates[CONTEXT_ALLOW_PATHS_KEY] = json.dumps(
            list(context_paths),
            separators=(",", ":"),
        )
    if context_mode is not None:
        updates[CONTEXT_MODE_KEY] = context_mode

    profile_result = write_profile(updates, path=path, merge=True, dry_run=dry_run)
    try:
        registration_result = preflight if dry_run else bootstrap(
            binary_path=binary_path, config_path=path,
            contexts=contexts, prepared=prepared, approvals=approvals,
        )
    except RegistrarError as error:
        return {
            "state": "registration_incomplete", "profile": profile_result,
            "registrations": {}, "reason_codes": [code.value for code in error.reason_codes],
            "next_action": "Profile update completed; registration did not start. Resolve the reported conflict before retrying.",
        }
    if not dry_run and any(
        item.outcome not in {Outcome.APPLIED, Outcome.NO_CHANGE}
        for item in registration_result.values()
    ):
        return {"state": "registration_incomplete", "registrations": registration_result,
                "profile": profile_result, "next_action": "Resolve the reported registration operation."}
    if dry_run:
        state = "would_setup"
    else:
        resolved = SnowKitConfig.from_env(config_path=path)
        state = "needs_sign_in" if resolved.account and resolved.user else "needs_setup"
    if context_repo is not None and not context_paths and not proposed_default:
        next_action = (
            "Governance markers were not found. Re-run setup with one or more exact "
            "--context-path Markdown allow patterns."
        )
    elif state == "needs_setup":
        next_action = "Re-run setup with at least --account and --user."
    elif dry_run:
        next_action = "Re-run without --dry-run to apply setup."
    else:
        next_action = "Run `snow-kit auth login`, then `snow-kit doctor --live`."
    return {
        "state": state,
        "profile": profile_result,
        "registrations": registration_result,
        "context_default_proposed": proposed_default,
        "next_action": next_action,
    }


def repair(
    *,
    binary_path: str | None = None,
    config_path: Path | None = None,
    dry_run: bool = False,
    contexts: Mapping[str, RegistrationContext] | None = None,
    prepared: Mapping[str, PreparedOperation] | None = None,
    approvals: Mapping[str, Approval] | None = None,
) -> dict[str, Any]:
    """Repair the secure profile and reconcile existing lifecycle registrations."""
    path = (config_path or default_config_path()).expanduser()
    preflight = bootstrap(
        binary_path=binary_path, config_path=path, dry_run=dry_run,
        contexts=contexts, prepared=prepared, approvals=approvals, _validate_only=True,
    )
    profile_result = repair_profile(path, dry_run=dry_run)
    try:
        registration_result = preflight if dry_run else bootstrap(
            binary_path=binary_path, config_path=path,
            contexts=contexts, prepared=prepared, approvals=approvals,
        )
    except RegistrarError as error:
        return {
            "state": "registration_incomplete", "profile": profile_result,
            "registrations": {}, "reason_codes": [code.value for code in error.reason_codes],
            "next_action": "Profile update completed; registration did not start. Resolve the reported conflict before retrying.",
        }
    if not dry_run and any(
        item.outcome not in {Outcome.APPLIED, Outcome.NO_CHANGE}
        for item in registration_result.values()
    ):
        return {"state": "registration_incomplete", "registrations": registration_result,
                "profile": profile_result, "next_action": "Resolve the reported registration operation."}
    lifecycle_state = (
        "would_repair"
        if dry_run
        else status(binary_path=binary_path, config_path=path, contexts=contexts)["state"]
    )
    return {
        "state": lifecycle_state,
        "profile": profile_result,
        "registrations": registration_result,
        "context": (
            context_source_status(SnowKitConfig.from_env(config_path=path)).to_dict()
            if not dry_run
            else {"state": "not_checked"}
        ),
    }


def status_all(
    *, cursor_path: Path, codex_path: Path, claude_path: Path,
    binary_path: str | None = None, config_path: Path | None = None,
    contexts: Mapping[str, RegistrationContext] | None = None,
) -> dict[str, dict[str, Any]]:
    """Report owned-projection health without returning native entry values."""
    paths = {"cursor": cursor_path, "codex": codex_path, "claude": claude_path}
    result: dict[str, dict[str, Any]] = {}
    for host, registrar in registrars().items():
        if contexts is None or host not in contexts:
            result[host] = {
                "present": None, "canonical": None, "read_only": None,
                "ownership": "unknown", "reason_codes": ["context_required"],
                "observations": {name: "unknown" for name in (
                    "registered", "enabled", "authenticated", "tools_discovered", "safe_read")},
            }
            continue
        context = contexts[host]
        desired = registration_definition(context.source_revision, binary_path, config_path=config_path)
        if (context.source_owner != "KleinPerkins/kp-mcp"
                or context.connection_id != "kp-mcp:snow-kit"
                or context.definition_digest != desired.digest):
            result[host] = {"present": None, "canonical": False, "read_only": False,
                            "ownership": "unknown", "reason_codes": ["owner_conflict"],
                            "observations": {name: "unknown" for name in (
                                "registered", "enabled", "authenticated", "tools_discovered", "safe_read")}}
            continue
        inspection = registrar.inspect_registration(paths[host], context=context)
        matched = inspection.owned_projection_match and not inspection.reason_codes
        result[host] = {
            "present": inspection.present, "canonical": matched,
            "read_only": matched, "ownership": inspection.ownership,
            "reason_codes": [code.value for code in inspection.reason_codes],
            "observations": inspection.to_dict()["observations"],
        }
    return result


def status(
    *,
    binary_path: str | None = None,
    config_path: Path | None = None,
    contexts: Mapping[str, RegistrationContext] | None = None,
) -> dict[str, Any]:
    """Return redacted lifecycle status for the real platform paths."""
    paths = default_platform_paths()
    path = (config_path or default_config_path()).expanduser()
    binary = binary_path or _default_binary()
    config_state = "ready"
    profile_version = None
    key_count = 0
    try:
        profile = load_profile(path)
        resolved_config = SnowKitConfig.from_env(config_path=path)
        profile_version = int(profile.get(PROFILE_VERSION_KEY, "0") or "0")
        key_count = len(profile)
        if not path.is_file() or not resolved_config.account or not resolved_config.user:
            config_state = "needs_setup"
    except (ConfigError, OSError, ValueError):
        config_state = "access_denied"
        resolved_config = SnowKitConfig()
    try:
        context = context_source_status(resolved_config)
    except (ConfigError, OSError, ValueError):
        context = context_source_status(SnowKitConfig())
    registrations = status_all(
        cursor_path=paths["cursor"],
        codex_path=paths["codex"],
        claude_path=paths["claude"],
        binary_path=binary,
        config_path=path, contexts=contexts,
    )
    if config_state == "ready" and not all(
        item["present"] and item["canonical"] and item["read_only"]
        for item in registrations.values()
    ):
        config_state = "needs_setup"
    return {
        "server": SERVER_NAME,
        "version": __version__,
        "state": config_state if config_state != "ready" else context.state,
        "binary": {
            "present": Path(binary).is_file(),
            "executable": os.access(binary, os.X_OK),
        },
        "config": {
            "location": "override" if config_path or os.environ.get(CONFIG_PATH_ENV) else "canonical",
            "present": path.exists(),
            "state": config_state,
            "version": profile_version,
            "key_count": key_count,
        },
        "registrations": registrations,
        "context": context.to_dict(),
        "write_posture": "fail-closed-read-only",
    }


def _assert_live_tool_success(result: Any, label: str) -> None:
    """Accept the kit's data envelope and reject transport/application errors."""
    content = getattr(result, "content", [])
    text = getattr(content[0], "text", "") if content else ""
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} returned a non-JSON payload") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned an invalid snow-kit payload")
    if getattr(result, "isError", False):
        error = payload.get("error")
        if error == "Auth":
            raise Auth(f"{label} requires Snowflake sign-in", op="doctor")
        if error == "Permission":
            raise Permission(f"{label} was denied by Snowflake", op="doctor")
        raise RuntimeError(f"{label} returned an MCP tool error")
    status = payload.get("status")
    if payload.get("error") or (status is not None and status != "ok"):
        raise RuntimeError(f"{label} returned a snow-kit error")
    if status is None and "data" not in payload:
        raise RuntimeError(f"{label} returned an unexpected snow-kit payload")


async def _live_doctor(binary: str, config_path: Path) -> dict[str, Any]:
    """Initialize the stdio server, assert read-only tools, and run safe reads."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from kp_mcp_bootstrap.docgen import mcp_tool_name

    child_env = dict(os.environ)
    child_env.pop(WRITE_FLAG, None)
    child_env[CONFIG_PATH_ENV] = str(config_path)
    params = StdioServerParameters(
        command=binary,
        args=["mcp", "--read-only"],
        env=child_env,
    )

    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            forbidden = {
                mcp_tool_name(spec.name)
                for spec in all_specs()
                if spec.posture in {"write", "destructive"}
            }
            exposed = sorted(names & forbidden)
            if exposed:
                raise RuntimeError(f"read-only MCP exposed forbidden tools: {exposed!r}")
            select_one = await session.call_tool("query_execute", {"query": "SELECT 1"})
            context = await session.call_tool(
                "query_execute",
                {
                    "query": (
                        "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), "
                        "CURRENT_DATABASE(), CURRENT_SCHEMA()"
                    )
                },
            )
            _assert_live_tool_success(select_one, "SELECT 1")
            _assert_live_tool_success(context, "current-context query")
            return {
                "initialize": "ok",
                "tool_count": len(names),
                "writes_absent": True,
                "select_one": "ok",
                "current_context": "ok",
            }


def doctor(
    *,
    binary_path: str | None = None,
    config_path: Path | None = None,
    contexts: Mapping[str, RegistrationContext] | None = None,
    live: bool = False,
    require_registrations: bool = True,
) -> dict[str, Any]:
    """Validate config, executable, registration, pin, and read-only posture."""
    binary = binary_path or _default_binary()
    path = (config_path or default_config_path()).expanduser()
    checks: dict[str, Any] = {}
    try:
        profile = load_profile(path)
        checks["config"] = {
            "ok": path.is_file(),
            "key_count": len(profile),
            "permissions": "private" if path.is_file() else "missing",
            "version": int(profile.get(PROFILE_VERSION_KEY, "0") or "0"),
            "compatibility": (
                "current"
                if profile.get(PROFILE_VERSION_KEY) == str(CURRENT_PROFILE_VERSION)
                else "legacy-unversioned"
            ),
        }
    except ConfigError as exc:
        checks["config"] = {"ok": False, "error": str(exc)}
    checks["executable"] = {
        "ok": Path(binary).is_file() and os.access(binary, os.X_OK),
        "version": __version__,
    }

    lifecycle = status(binary_path=binary, config_path=path, contexts=contexts)
    registrations = lifecycle["registrations"]
    registrations_ok = all(
        item["present"] and item["canonical"] and item["read_only"]
        for item in registrations.values()
    )
    checks["registrations"] = {
        "ok": registrations_ok if require_registrations else True,
        "required": require_registrations,
        "platforms": registrations,
    }
    checks["write_posture"] = {
        "ok": all(
            spec.posture not in {"write", "destructive"}
            or getattr(spec, "flag", None) == WRITE_FLAG
            for spec in all_specs()
        ),
        "mode": "fail-closed-read-only",
    }
    try:
        source_status = context_source_status(
            SnowKitConfig.from_env(config_path=path)
        )
        checks["context"] = {
            "ok": (
                not source_status.configured
                or source_status.state in {"ready", "freshness_unknown"}
            ),
            "required": source_status.configured,
            "state": source_status.state,
            "freshness": source_status.freshness,
            "document_count": source_status.document_count,
        }
    except (ConfigError, OSError, ValueError):
        checks["context"] = {
            "ok": False,
            "required": True,
            "state": "access_denied",
        }
    ready = all(item.get("ok", False) for item in checks.values())
    result: dict[str, Any] = {
        "server": SERVER_NAME,
        "version": __version__,
        "mode": "live" if live else "offline",
        "ready": ready,
        "state": "ready" if ready else "needs_setup",
        "checks": checks,
    }
    if live and ready:
        try:
            result["live"] = asyncio.run(_live_doctor(binary, path))
        except Exception as exc:  # noqa: BLE001 - doctor reports connector/transport failures.
            state = (
                "needs_sign_in"
                if isinstance(exc, Auth)
                else "access_denied"
                if isinstance(exc, Permission)
                else "context_unavailable"
            )
            result["live"] = {"ok": False, "error": type(exc).__name__, "state": state}
            result["ready"] = False
            result["state"] = state
        else:
            result["live"]["ok"] = True
    return result


def render(result: dict[str, Any]) -> str:
    """Render lifecycle output deterministically."""
    return stable_json(result)
