"""Per-profile, per-tool write authorization.

Every tool that *requires* authorization — i.e. carries an ``OpSpec.flag`` (which
is exactly every ``write`` / ``destructive`` op; read/admin ops carry none) — is
refused at the CLI / MCP execution boundary unless it is authorized for the
*active profile*. Authorization is a per-profile ``1`` / ``0`` config value:

* ``1`` — granted: the op may run for that profile.
* ``0`` / unset — denied (the default).

This is a profile-scoped, persistent grant — distinct from, and additive to, the
ADR-F5 ``GOOGLE_KIT_ENABLE_*`` environment overrides (which remain as a runtime
escape hatch; see :func:`google_kit.core.flags.ensure_enabled`).

Storage
-------
A per-profile JSON file under the resolved config dir::

    <config_dir>/authorizations/<profile>.json
    {"schema": 1, "tools": {"gmail.send": 1, "drive.create": 0, ...}}

``config_dir`` follows :func:`kp_mcp_bootstrap.config.load_config` (honoring
``GOOGLE_KIT_CONFIG_DIR`` / ``CHAOS_LABS_ROOT`` / the macOS default). A profile
created via :func:`seed_profile` (e.g. on first ``auth login``) starts with every
required tool set to ``0`` (default-deny). Writes are atomic (temp file + rename)
so two concurrent processes (two chats) can never observe a torn file.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator

from google_kit.core.errors import GoogleKitError

#: Subdirectory of the config dir holding one ``<profile>.json`` per profile.
AUTHZ_DIRNAME = "authorizations"

#: On-disk schema version for forward compatibility.
SCHEMA_VERSION = 1


def _config_dir(config_dir: Path | None = None) -> Path:
    """Resolve the config dir (explicit override wins; else env-derived default)."""
    from .personal_runtime import current, held
    runtime = current()
    if runtime is not None:
        if config_dir is not None and Path(config_dir) != runtime.directory.path:
            held("config_override_refused")
        runtime.check()
        return runtime.directory.path
    if config_dir is not None:
        return Path(config_dir)
    from kp_mcp_bootstrap.config import load_config

    return load_config().config_dir


def _validate_profile(profile: str) -> str:
    """Reject profile names that are not a single safe path segment.

    The profile is interpolated straight into a filesystem path
    (``<config_dir>/authorizations/<profile>.json`` and a sibling ``.lock``) and
    into the Keychain account namespace, so a name containing a path separator or
    NUL, equal to ``.`` / ``..``, or absolute could read/write an *arbitrary*
    grant file outside the config dir (``../../foo`` escapes; ``/abs`` resets the
    join). Authorization is the security boundary, so fail closed on anything that
    isn't a plain segment rather than silently touching the wrong file.
    """
    if (
        not isinstance(profile, str)
        or not profile
        or profile in (".", "..")
        or "/" in profile
        or "\\" in profile
        or "\x00" in profile
        or os.path.isabs(profile)
    ):
        raise GoogleKitError(
            f"invalid profile name {profile!r}: must be a single path segment "
            "(no '/', '\\', '..', NUL, or absolute paths)",
            op="authz",
        )
    return profile


def authz_path(profile: str, *, config_dir: Path | None = None) -> Path:
    """Absolute path to *profile*'s authorization file (not guaranteed to exist)."""
    return _config_dir(config_dir) / AUTHZ_DIRNAME / f"{_validate_profile(profile)}.json"


def resolve_active_profile(explicit: str | None = None) -> str:
    """Resolve the effective profile for an authorization check.

    Mirrors :func:`google_kit.core.auth.build_service_for_op` exactly so the grant
    consulted always matches the identity the call actually runs as: an explicit
    ``--profile`` wins, else the sandbox guardrail (``GOOGLE_KIT_SANDBOX=1``), else
    ``GOOGLE_KIT_PROFILE`` / ``"default"``.
    """
    from kp_mcp_bootstrap.config import load_config

    from google_kit.core.sandbox import resolve_profile

    from .personal_runtime import current, held
    runtime = current()
    if runtime is not None:
        if explicit is not None and explicit != runtime.profile:
            held("profile_override_refused")
        runtime.check()
        return runtime.profile
    return resolve_profile(explicit) or load_config().profile


def requires_authorization(spec: Any) -> bool:
    """True iff *spec* is a tool that requires per-profile write authorization.

    A tool requires authorization exactly when it declares an ``OpSpec.flag`` —
    the registry invariant is that every ``write`` / ``destructive`` op (and only
    those) carries one, while read / admin ops carry none.
    """
    return bool(getattr(spec, "flag", None))


def required_tool_names() -> list[str]:
    """Sorted names of every registered tool that requires authorization."""
    from google_kit.registry import all_specs

    return sorted(s.name for s in all_specs() if requires_authorization(s))


def _coerce_bit(value: Any) -> int:
    """Normalize an on-disk/CLI value to a strict ``0`` / ``1`` bit."""
    if value in (1, "1", True):
        return 1
    return 0


def _read_tools(profile: str, config_dir: Path | None = None) -> dict[str, int]:
    """Read the raw ``{tool: 0|1}`` map for *profile* (missing/corrupt ⇒ ``{}``)."""
    from .personal_runtime import current, held
    runtime = current()
    if runtime is not None:
        if profile != runtime.profile or (config_dir is not None and Path(config_dir) != runtime.directory.path):
            held("authorization_override_refused")
        return runtime.authorization_tools()
    path = authz_path(profile, config_dir=config_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tools = raw.get("tools") if isinstance(raw, dict) else None
    if not isinstance(tools, dict):
        return {}
    return {k: _coerce_bit(v) for k, v in tools.items() if isinstance(k, str)}


def load_authorizations(profile: str, *, config_dir: Path | None = None) -> dict[str, int]:
    """Return the persisted ``{tool: 0|1}`` grants for *profile* (missing ⇒ ``{}``)."""
    return _read_tools(profile, config_dir)


def is_authorized(profile: str, tool: str, *, config_dir: Path | None = None) -> bool:
    """True iff *profile* has explicitly granted (``1``) *tool*. Default-deny."""
    return _read_tools(profile, config_dir).get(tool, 0) == 1


@contextlib.contextmanager
def _profile_lock(profile: str, config_dir: Path | None = None) -> Iterator[None]:
    """Best-effort cross-process exclusive lock around a profile's read-modify-write.

    Serializes concurrent ``set_authorization`` / ``seed_profile`` on the same
    profile across processes (two chats), so a grant/revoke can't be lost to a
    last-writer-wins race (which, for a revoke, would fail *open*). Degrades to a
    no-op — relying on the atomic single write alone — when ``fcntl`` is
    unavailable or the directory is unwritable, so it never blocks or fails a
    write. Locks a sibling ``.lock`` file (not the data file, whose inode is
    swapped by ``os.replace``).
    """
    try:
        import fcntl
    except Exception:
        yield
        return
    path = authz_path(profile, config_dir=config_dir)
    lock_path = path.parent / f".{path.name}.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "w", encoding="utf-8")
    except OSError:
        yield
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError:
        handle.close()
        yield
        return
    try:
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* as JSON to *path* atomically (temp file + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        try:
            fh = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)  # fdopen failed to take ownership; close the raw fd
            raise
        with fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_tools(profile: str, tools: dict[str, int], config_dir: Path | None = None) -> Path:
    path = authz_path(profile, config_dir=config_dir)
    payload = {
        "schema": SCHEMA_VERSION,
        "tools": {k: _coerce_bit(v) for k, v in sorted(tools.items())},
    }
    _atomic_write(path, payload)
    return path


def set_authorization(
    profile: str, tool: str, value: Any, *, config_dir: Path | None = None
) -> Path:
    """Set *tool*'s grant for *profile* to ``1``/``0``, preserving other entries."""
    from .personal_runtime import current, held
    if current() is not None:
        held("personal_grant_mutation_refused")
    with _profile_lock(profile, config_dir=config_dir):
        tools = _read_tools(profile, config_dir)
        tools[tool] = _coerce_bit(value)
        return _write_tools(profile, tools, config_dir)


def seed_profile(
    profile: str, *, config_dir: Path | None = None, overwrite: bool = False
) -> Path:
    """Create *profile*'s authorization file with every required tool present.

    Idempotent: existing grants are preserved and any newly-registered tools are
    added at ``0`` (default-deny). With ``overwrite=True`` every entry is reset to
    ``0``. Returns the file path.
    """
    from .personal_runtime import current, held
    if current() is not None:
        held("personal_grant_mutation_refused")
    with _profile_lock(profile, config_dir=config_dir):
        existing = {} if overwrite else _read_tools(profile, config_dir)
        tools = {name: existing.get(name, 0) for name in required_tool_names()}
        return _write_tools(profile, tools, config_dir)


def authorization_view(
    profile: str, *, config_dir: Path | None = None
) -> dict[str, int]:
    """Complete ``{tool: 0|1}`` view for *profile*: every required tool, persisted
    grant or ``0`` default. Stable (sorted) for display / JSON output.
    """
    persisted = _read_tools(profile, config_dir)
    return {name: persisted.get(name, 0) for name in required_tool_names()}
