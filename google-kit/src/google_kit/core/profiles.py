"""Machine-local Google Docs style profile store.

Profiles live under the canonical google-kit config dir:

    <config_dir>/doc-styles/<name>.json

The store deliberately mirrors the authorization store's schema envelope,
single-segment name validation, best-effort lock, and atomic write helpers.
"""
from __future__ import annotations

import json
import os
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google_kit.core.audit import get_actor, write_audit
from google_kit.core.authz import (
    SCHEMA_VERSION,
    _atomic_write,
    _config_dir,
    _profile_lock,
    _validate_profile,
)
from google_kit.core.errors import GoogleKitError, NotFound, Validation

DOC_STYLES_DIRNAME = "doc-styles"
DEFAULT_NAME = "default"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_style_name(name: str) -> str:
    try:
        value = _validate_profile(name)
    except GoogleKitError as exc:
        raise Validation(exc.message, op="docs.styles") from exc
    if not value.isascii():
        raise Validation(
            f"invalid style profile name {name!r}: must contain only ASCII characters",
            op="docs.styles",
        )
    return value


def profiles_dir(*, config_dir: Path | None = None) -> Path:
    """Return the directory holding local style profiles."""
    return _config_dir(config_dir) / DOC_STYLES_DIRNAME


def profile_path(name: str, *, config_dir: Path | None = None) -> Path:
    """Return the absolute path for a style profile name."""
    return profiles_dir(config_dir=config_dir) / f"{_validate_style_name(name)}.json"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _ensure_private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def ensure_gitignored(path: Path) -> bool:
    """Ensure a profile path inside a git worktree is ignored before writing.

    Returns True when a git worktree was found and ignore coverage was verified.
    Returns False outside git. The guard writes a narrow local exclude entry
    (`.git/info/exclude`) rather than changing tracked files at runtime.
    """
    target = path.resolve()
    probe_dir = target.parent
    probe_dir.mkdir(parents=True, exist_ok=True)

    root_proc = subprocess.run(
        ["git", "-C", str(probe_dir), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if root_proc.returncode != 0:
        return False

    root = Path(root_proc.stdout.strip()).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False

    check = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode == 0:
        return True

    exclude = root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if "**/doc-styles/" not in existing:
        with open(exclude, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write("\n# google-kit local style profiles\n**/doc-styles/\n")

    recheck = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if recheck.returncode == 0:
        return True
    raise Validation(
        f"style profile path is inside git but is not ignored: {target}",
        op="docs.styles",
    )


def _validate_payload(raw: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise Validation(f"style profile {name!r} must be a JSON object", op="docs.styles")
    if raw.get("schema") != SCHEMA_VERSION:
        raise Validation(
            f"style profile {name!r} has unsupported schema {raw.get('schema')!r}",
            op="docs.styles",
        )
    named_styles = raw.get("named_styles")
    document_style = raw.get("document_style")
    if named_styles is not None and not isinstance(named_styles, dict):
        raise Validation(f"style profile {name!r} named_styles must be an object", op="docs.styles")
    if document_style is not None and not isinstance(document_style, dict):
        raise Validation(f"style profile {name!r} document_style must be an object", op="docs.styles")
    return dict(raw)


def load_profile(name: str = DEFAULT_NAME, *, config_dir: Path | None = None) -> dict[str, Any]:
    """Load and validate a local style profile."""
    path = profile_path(name, config_dir=config_dir)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise NotFound(f"style profile {name!r} not found", op="docs.styles") from exc
    except OSError as exc:
        raise Validation(f"could not read style profile {name!r}: {exc}", op="docs.styles") from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise Validation(f"style profile {name!r} is corrupt JSON: {exc.msg}", op="docs.styles") from exc
    return _validate_payload(raw, name=name)


def save_profile(
    name: str,
    profile: dict[str, Any],
    *,
    config_dir: Path | None = None,
    audit: bool = True,
) -> Path:
    """Persist a style profile atomically with private file permissions."""
    name = _validate_style_name(name)
    path = profile_path(name, config_dir=config_dir)
    _ensure_private_dir(path.parent)
    ensure_gitignored(path)

    payload = deepcopy(profile)
    payload["schema"] = SCHEMA_VERSION
    payload.setdefault("created_at", _utc_now_iso())

    with _profile_lock(name, config_dir=config_dir):
        _atomic_write(path, payload)
        _ensure_private_file(path)

    if audit:
        write_audit(
            actor=get_actor(),
            op="docs.styles.save",
            normalized_request={"style_profile": name},
            target_ids=[
                str(v)
                for v in (payload.get("source_doc_id"), payload.get("template_doc_id"))
                if v
            ],
            result="ok",
        )
    return path


def delete_profile(name: str, *, config_dir: Path | None = None) -> bool:
    """Delete a profile if it exists."""
    name = _validate_style_name(name)
    path = profile_path(name, config_dir=config_dir)
    ensure_gitignored(path)
    with _profile_lock(name, config_dir=config_dir):
        try:
            path.unlink()
            deleted = True
        except FileNotFoundError:
            deleted = False
    write_audit(
        actor=get_actor(),
        op="docs.styles.delete",
        normalized_request={"style_profile": name},
        target_ids=[],
        result="ok" if deleted else "skipped",
    )
    return deleted


def list_profiles(*, config_dir: Path | None = None) -> list[str]:
    """List local style profile names in stable order."""
    root = profiles_dir(config_dir=config_dir)
    if not root.exists():
        return []
    return sorted(p.stem for p in root.glob("*.json") if p.is_file())


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def apply_overrides(
    profile: dict[str, Any] | None,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return profile data with inline style overrides layered on top."""
    base = deepcopy(profile or starter_profile())
    if overrides:
        base = _deep_merge(base, overrides)
    base["schema"] = SCHEMA_VERSION
    return base


def resolve_profile_name(explicit: str | None, *, allow_env: bool = False) -> str | None:
    """Resolve an explicit selector plus the optional env default."""
    if explicit is not None:
        value = explicit.strip()
        if value.lower() == "legacy":
            return None
        return _validate_style_name(value)
    if allow_env:
        env_value = os.environ.get("GOOGLE_KIT_DEFAULT_STYLE_PROFILE")
        if env_value:
            value = env_value.strip()
            if value.lower() == "legacy":
                return None
            return _validate_style_name(value)
    return None


def load_for_selector(
    explicit: str | None,
    *,
    allow_env: bool = False,
    config_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Load a profile selected by explicit arg or env default, or return None.

    There is no silent ambient ``default.json`` load. Callers that need the
    on-disk ``default`` profile must pass it explicitly or set
    ``GOOGLE_KIT_DEFAULT_STYLE_PROFILE``.
    """
    name = resolve_profile_name(explicit, allow_env=allow_env)
    if name is None:
        return None
    return load_profile(name, config_dir=config_dir)


def describe_applied_profile(
    *,
    explicit: str | None,
    resolved_name: str | None,
) -> str | None:
    """Return the profile label echoed in apply-style operation output."""
    if explicit is not None:
        value = explicit.strip()
        if value.lower() == "legacy":
            return "legacy"
        return value
    return resolved_name


def starter_profile() -> dict[str, Any]:
    """Return the shipped blank-slate starter profile."""
    template = (
        Path(__file__).parent.parent
        / "services"
        / "docs"
        / "templates"
        / "starter_style_profile.json"
    )
    try:
        raw = json.loads(template.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {
            "schema": SCHEMA_VERSION,
            "named_styles": {},
            "document_style": {
                "documentFormat": {"documentMode": "PAGES"},
                "marginTop": {"magnitude": 72, "unit": "PT"},
                "marginBottom": {"magnitude": 72, "unit": "PT"},
                "marginLeft": {"magnitude": 72, "unit": "PT"},
                "marginRight": {"magnitude": 72, "unit": "PT"},
            },
        }
    return _validate_payload(raw, name="starter")


def doctor_profiles(*, config_dir: Path | None = None, seed_default: bool = True) -> dict[str, Any]:
    """Validate local profiles and optionally seed a starter default."""
    root = profiles_dir(config_dir=config_dir)
    _ensure_private_dir(root)
    valid: list[str] = []
    quarantined: list[str] = []
    for path in sorted(root.glob("*.json")):
        name = path.stem
        try:
            load_profile(name, config_dir=config_dir)
            valid.append(name)
        except (Validation, NotFound):
            quarantine = path.with_suffix(path.suffix + ".corrupt")
            path.replace(quarantine)
            quarantined.append(path.name)

    if seed_default and DEFAULT_NAME not in valid and not profile_path(DEFAULT_NAME, config_dir=config_dir).exists():
        save_profile(DEFAULT_NAME, starter_profile(), config_dir=config_dir)
        valid.append(DEFAULT_NAME)

    return {
        "profiles_dir": str(root),
        "valid": sorted(set(valid)),
        "quarantined": quarantined,
        "default": os.environ.get("GOOGLE_KIT_DEFAULT_STYLE_PROFILE") or DEFAULT_NAME,
    }
