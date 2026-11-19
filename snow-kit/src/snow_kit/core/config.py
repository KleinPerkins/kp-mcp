"""Strict operator-local configuration for snow-kit.

Runtime precedence is process environment, then the canonical mode-0600 profile,
then neutral defaults.  Profiles are parsed as data (never sourced as shell) and
may contain only the documented allowlisted keys.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_MCP_SERVER_NAME = "snow-kit"
WRITE_FLAG = "SNOW_KIT_ENABLE_WRITE"
CONFIG_PATH_ENV = "SNOW_KIT_CONFIG_PATH"
PROFILE_VERSION_KEY = "SNOW_KIT_PROFILE_VERSION"
CURRENT_PROFILE_VERSION = 1
CONTEXT_REPO_KEY = "SNOW_KIT_CONTEXT_REPO"
CONTEXT_ALLOW_PATHS_KEY = "SNOW_KIT_CONTEXT_ALLOW_PATHS"
CONTEXT_MODE_KEY = "SNOW_KIT_CONTEXT_MODE"
_MAX_PROFILE_BYTES = 64 * 1024
_PROFILE_KEYS = frozenset(
    {
        PROFILE_VERSION_KEY,
        "SNOW_KIT_USER",
        "SNOW_KIT_ACCOUNT",
        "SNOW_KIT_AUTHENTICATOR",
        "SNOW_KIT_WAREHOUSE",
        "SNOW_KIT_DATABASE",
        "SNOW_KIT_SCHEMA",
        "SNOW_KIT_ROLE",
        "SNOW_KIT_LOGIN_TIMEOUT",
        "SNOW_KIT_NETWORK_TIMEOUT",
        "SNOW_KIT_QUERY_TIMEOUT",
        "SNOW_KIT_TOOL_TIMEOUT",
        "SNOW_KIT_AUTH_LOCK_TIMEOUT",
        "SNOW_KIT_MAX_RESULT_ROWS",
        "SNOW_KIT_MAX_RECONNECT_RETRIES",
        "SNOW_KIT_PERMISSION_SPEC_PATH",
        "SNOW_KIT_WRITE_SCHEMA_PATTERNS",
        "SNOW_KIT_STATE_DIR",
        "SNOW_KIT_AUTH_LOCK_DIR",
        CONTEXT_REPO_KEY,
        CONTEXT_ALLOW_PATHS_KEY,
        CONTEXT_MODE_KEY,
    }
)


class ConfigError(ValueError):
    """Raised when the local profile is unsafe or invalid."""


def default_config_path() -> Path:
    """Return the canonical operator-local profile path."""
    configured = os.environ.get(CONFIG_PATH_ENV)
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ConfigError(f"{CONFIG_PATH_ENV} must be an absolute path")
        return path
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
    if not root.is_absolute():
        raise ConfigError("XDG_CONFIG_HOME must be an absolute path")
    return root / "snow-kit" / "config.env"


def profile_keys() -> frozenset[str]:
    """Return the supported profile key allowlist."""
    return _PROFILE_KEYS


def _decode_profile_value(raw: str, *, line_number: int) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise ConfigError(f"config line {line_number}: unterminated quoted value")
        value = value[1:-1]
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ConfigError(f"config line {line_number}: invalid control character")
    return value


def _secure_profile_text(path: Path) -> str | None:
    """Read a regular, operator-owned, non-symlink profile with private permissions."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ConfigError("config must be a regular non-symlink file")
    if hasattr(os, "getuid") and before.st_uid != os.getuid():
        raise ConfigError("config must be owned by the current user")
    if stat.S_IMODE(before.st_mode) & 0o077:
        raise ConfigError("config permissions must be 0600 or stricter")
    if before.st_size > _MAX_PROFILE_BYTES:
        raise ConfigError(f"config exceeds {_MAX_PROFILE_BYTES} bytes")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ConfigError("could not securely open the snow-kit config") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise ConfigError("config changed while being opened")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            return handle.read(_MAX_PROFILE_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)


def load_profile(path: Path | None = None) -> dict[str, str]:
    """Load and validate the canonical dotenv-style profile."""
    profile_path = (path or default_config_path()).expanduser()
    text = _secure_profile_text(profile_path)
    if text is None:
        return {}
    if len(text.encode("utf-8")) > _MAX_PROFILE_BYTES:
        raise ConfigError(f"config exceeds {_MAX_PROFILE_BYTES} bytes")
    return _parse_profile_text(text)


def _parse_profile_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"config line {line_number}: expected KEY=VALUE")
        key, _, value = line.partition("=")
        key = key.strip()
        if key == WRITE_FLAG:
            raise ConfigError(f"{WRITE_FLAG} is forbidden in snow-kit profiles")
        if key not in _PROFILE_KEYS:
            raise ConfigError(f"config line {line_number}: unsupported key {key!r}")
        if key in values:
            raise ConfigError(f"config line {line_number}: duplicate key {key!r}")
        values[key] = _decode_profile_value(value, line_number=line_number)
    return values


def _validate_profile_values(values: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    unsupported = set(values) - _PROFILE_KEYS
    if WRITE_FLAG in values:
        unsupported.add(WRITE_FLAG)
    if unsupported:
        raise ConfigError(f"unsupported snow-kit profile keys: {sorted(unsupported)!r}")
    for key, raw in values.items():
        if not isinstance(raw, str):
            raise ConfigError(f"profile value for {key} must be a string")
        if any(char in raw for char in ("\x00", "\n", "\r")):
            raise ConfigError(f"profile value for {key} contains a control character")
        normalized[key] = raw.strip()
    _parse_profile_version(normalized)
    _parse_context_allow_paths(normalized)
    _parse_context_mode(normalized)
    repo = normalized.get(CONTEXT_REPO_KEY)
    if repo:
        path = Path(repo).expanduser()
        if not path.is_absolute():
            raise ConfigError(f"{CONTEXT_REPO_KEY} must be an absolute path")
    spec = normalized.get("SNOW_KIT_PERMISSION_SPEC_PATH")
    if spec:
        spec_path = Path(spec).expanduser()
        if not spec_path.is_absolute():
            raise ConfigError("SNOW_KIT_PERMISSION_SPEC_PATH must be an absolute path")
    return normalized


def write_profile(
    values: Mapping[str, str],
    *,
    path: Path | None = None,
    merge: bool = True,
    dry_run: bool = False,
) -> dict[str, object]:
    """Atomically write a private dotenv profile without exposing its values."""
    profile_path = (path or default_config_path()).expanduser()
    if not profile_path.is_absolute():
        raise ConfigError("snow-kit profile path must be absolute")
    current = load_profile(profile_path) if merge else {}
    merged = dict(current)
    merged.update(values)
    merged.setdefault(PROFILE_VERSION_KEY, str(CURRENT_PROFILE_VERSION))
    validated = _validate_profile_values(merged)
    text = "".join(f"{key}={validated[key]}\n" for key in sorted(validated))
    if len(text.encode("utf-8")) > _MAX_PROFILE_BYTES:
        raise ConfigError(f"config exceeds {_MAX_PROFILE_BYTES} bytes")
    if not dry_run:
        profile_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent_info = profile_path.parent.lstat()
        if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
            raise ConfigError("snow-kit config directory must be a regular non-symlink directory")
        if hasattr(os, "getuid") and parent_info.st_uid != os.getuid():
            raise ConfigError("snow-kit config directory must be owned by the current user")
        os.chmod(profile_path.parent, 0o700)
        try:
            existing_info = profile_path.lstat()
        except FileNotFoundError:
            existing_info = None
        if existing_info and (
            stat.S_ISLNK(existing_info.st_mode)
            or not stat.S_ISREG(existing_info.st_mode)
        ):
            raise ConfigError("refusing to replace a non-regular or symlink snow-kit profile")
        fd, temp_name = tempfile.mkstemp(
            prefix=".config.env.",
            dir=profile_path.parent,
            text=True,
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, profile_path)
            os.chmod(profile_path, 0o600)
            directory_fd = os.open(profile_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    return {
        "location": "configured",
        "state": "would_update" if dry_run else "ready",
        "key_count": len(validated),
        "version": CURRENT_PROFILE_VERSION,
    }


def repair_profile(path: Path | None = None, *, dry_run: bool = False) -> dict[str, object]:
    """Repair safe ownership/permissions and normalize an existing profile."""
    profile_path = (path or default_config_path()).expanduser()
    try:
        info = profile_path.lstat()
    except FileNotFoundError:
        return write_profile({}, path=profile_path, merge=False, dry_run=dry_run)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ConfigError("refusing to repair a non-regular or symlink snow-kit profile")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ConfigError("refusing to repair a snow-kit profile owned by another user")
    if not dry_run:
        os.chmod(profile_path, 0o600)
    values = load_profile(profile_path) if not dry_run else _load_profile_for_repair(profile_path)
    return write_profile(values, path=profile_path, merge=False, dry_run=dry_run)


def _load_profile_for_repair(path: Path) -> dict[str, str]:
    """Parse a structurally checked repair candidate without changing its mode."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            text = handle.read(_MAX_PROFILE_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(text.encode("utf-8")) > _MAX_PROFILE_BYTES:
        raise ConfigError(f"config exceeds {_MAX_PROFILE_BYTES} bytes")
    return _parse_profile_text(text)


def _process_value(name: str) -> str | None:
    """Read a process override, preserving legacy SNOWFLAKE_* compatibility."""
    value = os.environ.get(name)
    if value:
        return value
    legacy = os.environ.get(name.replace("SNOW_KIT_", "SNOWFLAKE_"))
    return legacy or None


def _setting(
    name: str,
    profile: dict[str, str],
    default: str | None = None,
) -> str | None:
    process = _process_value(name)
    if process is not None:
        return process
    profile_value = profile.get(name)
    if profile_value:
        return profile_value
    return default


def _user_from_registered_mcp(*, cursor_path: Path | None = None) -> str | None:
    """Read ``SNOW_KIT_USER`` from an existing Cursor MCP registration."""
    path = cursor_path or (Path.home() / ".cursor" / "mcp.json")
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    env = data.get("mcpServers", {}).get(_MCP_SERVER_NAME, {}).get("env") or {}
    user = env.get("SNOW_KIT_USER")
    return user if isinstance(user, str) and user else None


def resolve_snowflake_user(
    *,
    config_path: Path | None = None,
    cursor_path: Path | None = None,
) -> str | None:
    """Resolve username for migration/bootstrap without embedding it in registrations.

    Precedence:
    1. ``SNOW_KIT_USER`` env, else ``SNOWFLAKE_USER`` env
    2. Selected snow-kit profile
    3. ``SNOW_KIT_USER`` already present in ``~/.cursor/mcp.json`` for snow-kit
    """
    explicit = _process_value("SNOW_KIT_USER")
    if explicit:
        return explicit
    profile_user = load_profile(config_path).get("SNOW_KIT_USER")
    if profile_user:
        return profile_user
    return _user_from_registered_mcp(cursor_path=cursor_path)


def bootstrap_env(*, config_path: Path | None = None) -> dict[str, str]:
    """Return the sole non-secret environment pointer stored in registrations."""
    path = (config_path or default_config_path()).expanduser()
    if not path.is_absolute():
        raise ConfigError("snow-kit registration config path must be absolute")
    return {CONFIG_PATH_ENV: str(path)}


def _setting_int(name: str, profile: dict[str, str], default: int) -> int:
    raw = _setting(name, profile)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {raw!r}")
    return value


def _parse_profile_version(profile: Mapping[str, str]) -> int:
    raw = profile.get(PROFILE_VERSION_KEY)
    if not raw:
        return 0
    try:
        version = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{PROFILE_VERSION_KEY} must be an integer") from exc
    if version != CURRENT_PROFILE_VERSION:
        raise ConfigError(
            f"unsupported snow-kit profile version {version}; expected {CURRENT_PROFILE_VERSION}"
        )
    return version


def _parse_context_allow_paths(profile: Mapping[str, str]) -> tuple[str, ...]:
    raw = profile.get(CONTEXT_ALLOW_PATHS_KEY, "")
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{CONTEXT_ALLOW_PATHS_KEY} must be a JSON array") from exc
    if (
        not isinstance(values, list)
        or not values
        or len(values) > 32
        or any(not isinstance(item, str) or not item.strip() for item in values)
    ):
        raise ConfigError(
            f"{CONTEXT_ALLOW_PATHS_KEY} must contain 1-32 non-empty path strings"
        )
    normalized = tuple(item.strip().replace("\\", "/") for item in values)
    for pattern in normalized:
        parts = pattern.split("/")
        if (
            len(pattern) > 256
            or len(parts) > 32
            or parts.count("**") > 2
            or pattern.startswith("/")
            or "\x00" in pattern
            or any(part in {"", ".", ".."} for part in parts)
            or not pattern.lower().endswith(".md")
        ):
            raise ConfigError(
                f"{CONTEXT_ALLOW_PATHS_KEY} contains an unsafe Markdown path pattern"
            )
    return normalized


def _parse_context_mode(profile: Mapping[str, str]) -> str:
    mode = profile.get(CONTEXT_MODE_KEY, "warn").strip().lower() or "warn"
    if mode not in {"off", "warn", "strict"}:
        raise ConfigError(f"{CONTEXT_MODE_KEY} must be off, warn, or strict")
    return mode


@dataclass(frozen=True)
class SnowKitConfig:
    """Resolved runtime config; secret-like values are never logged."""

    user: str | None = None
    account: str | None = None
    authenticator: str = "externalbrowser"
    warehouse: str | None = None
    database: str | None = None
    schema: str | None = None
    role: str | None = None
    login_timeout_seconds: int = 60
    network_timeout_seconds: int = 25
    statement_timeout_seconds: int = 25
    tool_timeout_seconds: int = 25
    auth_lock_timeout_seconds: int = 60
    max_result_rows: int = 10_000
    max_reconnect_retries: int = 2
    spec_path: Path | None = None
    write_schema_patterns: tuple[str, ...] = ()
    state_dir: Path | None = None
    auth_lock_dir: Path | None = None
    profile_version: int = 0
    context_repo: Path | None = None
    context_allow_paths: tuple[str, ...] = ()
    context_mode: str = "warn"

    @classmethod
    def from_env(cls, *, config_path: Path | None = None) -> "SnowKitConfig":
        profile = load_profile(config_path)
        profile_version = _parse_profile_version(profile)
        spec_raw = _setting("SNOW_KIT_PERMISSION_SPEC_PATH", profile)
        patterns = tuple(
            p.strip().upper()
            for p in (_setting("SNOW_KIT_WRITE_SCHEMA_PATTERNS", profile, "") or "").split(",")
            if p.strip()
        )
        context_repo_raw = _setting(CONTEXT_REPO_KEY, profile)
        context_repo = Path(context_repo_raw).expanduser() if context_repo_raw else None
        if context_repo is not None and not context_repo.is_absolute():
            raise ConfigError(f"{CONTEXT_REPO_KEY} must be an absolute path")
        spec_path = Path(spec_raw).expanduser() if spec_raw else None
        if spec_path is not None and not spec_path.is_absolute():
            raise ConfigError("SNOW_KIT_PERMISSION_SPEC_PATH must be an absolute path")
        return cls(
            user=_setting("SNOW_KIT_USER", profile),
            account=_setting("SNOW_KIT_ACCOUNT", profile),
            authenticator=_setting("SNOW_KIT_AUTHENTICATOR", profile, "externalbrowser")
            or "externalbrowser",
            warehouse=_setting("SNOW_KIT_WAREHOUSE", profile),
            database=_setting("SNOW_KIT_DATABASE", profile),
            schema=_setting("SNOW_KIT_SCHEMA", profile),
            role=_setting("SNOW_KIT_ROLE", profile),
            login_timeout_seconds=_setting_int("SNOW_KIT_LOGIN_TIMEOUT", profile, 60),
            network_timeout_seconds=_setting_int("SNOW_KIT_NETWORK_TIMEOUT", profile, 25),
            statement_timeout_seconds=_setting_int("SNOW_KIT_QUERY_TIMEOUT", profile, 25),
            tool_timeout_seconds=_setting_int("SNOW_KIT_TOOL_TIMEOUT", profile, 25),
            auth_lock_timeout_seconds=_setting_int("SNOW_KIT_AUTH_LOCK_TIMEOUT", profile, 60),
            max_result_rows=_setting_int("SNOW_KIT_MAX_RESULT_ROWS", profile, 10_000),
            max_reconnect_retries=_setting_int("SNOW_KIT_MAX_RECONNECT_RETRIES", profile, 2),
            spec_path=spec_path,
            write_schema_patterns=patterns,
            state_dir=(
                Path(raw).expanduser()
                if (raw := _setting("SNOW_KIT_STATE_DIR", profile))
                else None
            ),
            auth_lock_dir=(
                Path(raw).expanduser()
                if (raw := _setting("SNOW_KIT_AUTH_LOCK_DIR", profile))
                else None
            ),
            profile_version=profile_version,
            context_repo=context_repo,
            context_allow_paths=_parse_context_allow_paths(
                {
                    CONTEXT_ALLOW_PATHS_KEY: (
                        _setting(CONTEXT_ALLOW_PATHS_KEY, profile, "") or ""
                    )
                }
            ),
            context_mode=_parse_context_mode(
                {CONTEXT_MODE_KEY: _setting(CONTEXT_MODE_KEY, profile, "warn") or "warn"}
            ),
        )

    def connector_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {"authenticator": self.authenticator}
        for key, value in (
            ("user", self.user),
            ("account", self.account),
            ("warehouse", self.warehouse),
            ("database", self.database),
            ("schema", self.schema),
            ("role", self.role),
        ):
            if value:
                kwargs[key] = value
        return kwargs

    def redacted(self) -> dict[str, object]:
        values: dict[str, object] = {
            key: (
                value
                if key == "authenticator"
                else "configured"
            )
            for key, value in self.connector_kwargs().items()
        }
        values["context"] = {
            "configured": bool(self.context_repo and self.context_allow_paths),
            "allow_pattern_count": len(self.context_allow_paths),
            "mode": self.context_mode,
        }
        return values
