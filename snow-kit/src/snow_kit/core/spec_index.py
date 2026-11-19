"""Strict, explanatory index for the nested Permifrost permission spec shape."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_SHELVES = ("teams", "services", "data")
_TOP_LEVEL_KEYS = frozenset({"roles", "users"})
_ROLE_KEYS = frozenset({"member_of", "privileges", "warehouses", "abstract"})
_USER_KEYS = frozenset({"can_login", "member_of"})
_OBJECT_TYPES = {"databases": 1, "schemas": 2, "tables": 3}
_ACCESS_LEVELS = frozenset({"read", "write"})
_WRITE_OPERATIONS = frozenset(
    {
        "CREATE",
        "CREATE TABLE",
        "DELETE",
        "INSERT",
        "MERGE",
        "TRUNCATE",
        "UPDATE",
        "WRITE",
    }
)
_MAX_SPEC_BYTES = 2 * 1024 * 1024
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_+/'-]+$|^\*$")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


@dataclass(frozen=True)
class SpecMatch:
    role: str
    privilege: str
    object_pattern: str
    object_type: str
    source: str
    notes: list[str] = field(default_factory=list)


@dataclass
class SpecExplanation:
    available: bool
    root: str | None
    revision: str | None = None
    matched: list[SpecMatch] = field(default_factory=list)
    roles_for_email: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _ParsedSpec:
    matches: tuple[SpecMatch, ...]
    parents: dict[str, tuple[str, ...]]
    users: dict[str, tuple[str, ...]]
    warnings: tuple[str, ...]


class SpecIndex:
    """Index actual Permifrost roles/users/privileges for explanation only."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        self.available = bool(root and root.is_dir() and not root.is_symlink())
        self.revision: str | None = None
        self._parsed = _ParsedSpec((), {}, {}, ())
        if self.available and root is not None:
            cache_key = _revision_key(root)
            self.revision = (
                cache_key.split(":", 1)[0]
                if re.match(r"^[a-f0-9]{40,64}:", cache_key)
                else cache_key
            )
            self._parsed = _load_revision(str(root.resolve()), cache_key)

    def explain(
        self,
        *,
        object_name: str,
        operation: str,
        role: str | None = None,
        email: str | None = None,
    ) -> SpecExplanation:
        wanted = object_name.upper()
        op = operation.upper().strip()
        direct_email_roles = self._parsed.users.get((email or "").lower(), ())
        email_roles = _role_closure(direct_email_roles, self._parsed.parents)
        requested_role = role.upper().strip() if role else None
        effective_roles: set[str] | None = None
        if requested_role:
            effective_roles = _role_closure((requested_role,), self._parsed.parents)
        elif email:
            effective_roles = email_roles
        matched: list[SpecMatch] = []
        for match in self._parsed.matches:
            if effective_roles is not None and match.role not in effective_roles:
                continue
            if not _privilege_matches(match.privilege, op):
                continue
            if not _pattern_matches(match.object_pattern, wanted):
                continue
            notes = list(match.notes)
            if requested_role and match.role != requested_role:
                notes.append(f"inherited through {requested_role}")
            matched.append(
                SpecMatch(
                    role=match.role,
                    privilege=match.privilege,
                    object_pattern=match.object_pattern,
                    object_type=match.object_type,
                    source=match.source,
                    notes=notes,
                )
            )
        matched.sort(
            key=lambda item: (
                item.role,
                item.object_type,
                item.object_pattern,
                item.privilege,
                item.source,
            )
        )
        return SpecExplanation(
            available=self.available,
            root="configured" if self.root else None,
            revision=self.revision,
            matched=matched,
            roles_for_email=sorted(email_roles),
            warnings=list(self._parsed.warnings),
        )


@lru_cache(maxsize=8)
def _load_revision(root_text: str, revision: str) -> _ParsedSpec:
    root = Path(root_text)
    try:
        import yaml
    except Exception:
        return _ParsedSpec(
            (),
            {},
            {},
            ("PyYAML unavailable; permission-spec explanations are disabled.",),
        )

    matches: list[SpecMatch] = []
    parents: dict[str, set[str]] = {}
    users: dict[str, set[str]] = {}
    warnings: list[str] = []
    if ":dirty:" in revision:
        warnings.append(
            "Permission specs have local changes; explanations may not match committed policy."
        )
    base = root / "specs" / "prod" / "us"
    root_resolved = root.resolve()
    paths: list[Path] = []
    for shelf in _SHELVES:
        shelf_root = base / shelf
        if not shelf_root.is_dir():
            continue
        for entry in shelf_root.rglob("*"):
            if not entry.is_symlink():
                continue
            source = _EMAIL_RE.sub(
                "[redacted-email]",
                entry.relative_to(root).as_posix(),
            )
            if entry.is_dir():
                try:
                    entry.resolve().relative_to(root_resolved)
                except (OSError, ValueError):
                    warnings.append(
                        f"Skipped permission spec outside configured root: {source}"
                    )
                continue
            if entry.suffix.lower() in {".yml", ".yaml"}:
                warnings.append(f"Skipped symlink permission spec: {source}")
        paths.extend(shelf_root.rglob("*.yml"))
        paths.extend(shelf_root.rglob("*.yaml"))
    for path in sorted(set(paths), key=lambda item: item.as_posix()):
        source = _EMAIL_RE.sub(
            "[redacted-email]",
            path.relative_to(root).as_posix(),
        )
        if path.is_symlink():
            warnings.append(f"Skipped symlink permission spec: {source}")
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root_resolved)
        except (OSError, ValueError):
            warnings.append(f"Skipped permission spec outside configured root: {source}")
            continue
        try:
            if path.stat().st_size > _MAX_SPEC_BYTES:
                warnings.append(f"Skipped oversized permission spec: {source}")
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001 - live Snowflake grants remain decisive.
            warnings.append(f"Skipped invalid permission spec {source}: {type(exc).__name__}")
            continue
        _parse_document(
            data,
            source=source,
            matches=matches,
            parents=parents,
            users=users,
            warnings=warnings,
        )
    return _ParsedSpec(
        matches=tuple(matches),
        parents={key: tuple(sorted(value)) for key, value in parents.items()},
        users={key: tuple(sorted(value)) for key, value in users.items()},
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _parse_document(
    data: Any,
    *,
    source: str,
    matches: list[SpecMatch],
    parents: dict[str, set[str]],
    users: dict[str, set[str]],
    warnings: list[str],
) -> None:
    if not isinstance(data, dict) or not data or not set(data).issubset(_TOP_LEVEL_KEYS):
        warnings.append(f"Skipped unknown permission schema: {source}")
        return
    for role_name, body in _singleton_entries(data.get("roles"), source, "roles", warnings):
        role = role_name.upper()
        if not isinstance(body, dict) or not set(body).issubset(_ROLE_KEYS):
            warnings.append(f"Skipped role with unknown schema in {source}: {role}")
            continue
        parent_values = body.get("member_of", [])
        if not _string_list(parent_values):
            warnings.append(f"Skipped invalid member_of for role in {source}: {role}")
            continue
        parents.setdefault(role, set()).update(value.upper() for value in parent_values)
        privileges = body.get("privileges")
        if privileges is None:
            continue
        if not isinstance(privileges, dict) or not set(privileges).issubset(_OBJECT_TYPES):
            warnings.append(f"Skipped unknown privileges schema in {source}: {role}")
            continue
        for object_type, levels in privileges.items():
            if not isinstance(levels, dict) or not set(levels).issubset(_ACCESS_LEVELS):
                warnings.append(
                    f"Skipped unknown {object_type} privilege schema in {source}: {role}"
                )
                continue
            for access, patterns in levels.items():
                if not _string_list(patterns):
                    warnings.append(
                        f"Skipped invalid {object_type}.{access} list in {source}: {role}"
                    )
                    continue
                for pattern in patterns:
                    normalized = pattern.upper()
                    if not _valid_pattern(normalized, _OBJECT_TYPES[object_type]):
                        warnings.append(
                            f"Skipped invalid {object_type} pattern in {source}: {role}"
                        )
                        continue
                    matches.append(
                        SpecMatch(
                            role=role,
                            privilege=access.upper(),
                            object_pattern=normalized,
                            object_type=object_type[:-1],
                            source=source,
                        )
                    )
    for email, body in _singleton_entries(data.get("users"), source, "users", warnings):
        if not isinstance(body, dict) or not set(body).issubset(_USER_KEYS):
            warnings.append(f"Skipped user with unknown schema in {source}")
            continue
        memberships = body.get("member_of", [])
        if not _string_list(memberships):
            warnings.append(f"Skipped user with invalid member_of in {source}")
            continue
        if "@" not in email:
            # Permifrost also permits service usernames. They remain indexed by
            # exact identifier but are not surfaced as owner/contact metadata.
            user_key = email.lower()
        else:
            user_key = email.lower()
        users.setdefault(user_key, set()).update(value.upper() for value in memberships)


def _singleton_entries(
    value: Any,
    source: str,
    label: str,
    warnings: list[str],
) -> list[tuple[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        warnings.append(f"Skipped non-list {label} in {source}")
        return []
    entries: list[tuple[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or len(item) != 1:
            warnings.append(f"Skipped malformed {label} entry in {source}")
            continue
        name, body = next(iter(item.items()))
        if not isinstance(name, str) or not name.strip():
            warnings.append(f"Skipped unnamed {label} entry in {source}")
            continue
        entries.append((name.strip(), body))
    return entries


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _valid_pattern(pattern: str, segment_count: int) -> bool:
    segments = pattern.split(".")
    return len(segments) == segment_count and all(
        bool(_SEGMENT_RE.fullmatch(segment)) for segment in segments
    )


def _privilege_matches(privilege: str, operation: str) -> bool:
    if privilege == "READ":
        return operation in {"READ", "SELECT"}
    if privilege == "WRITE":
        return operation in _WRITE_OPERATIONS or operation.split(maxsplit=1)[0] in _WRITE_OPERATIONS
    return False


def _pattern_matches(pattern: str, value: str) -> bool:
    pattern_segments = pattern.split(".")
    value_segments = value.split(".")
    return len(pattern_segments) == len(value_segments) and all(
        expected == "*" or expected == actual
        for expected, actual in zip(pattern_segments, value_segments)
    )


def _role_closure(
    roots: tuple[str, ...] | list[str],
    parents: dict[str, tuple[str, ...]],
) -> set[str]:
    seen: set[str] = set()
    pending = [role.upper() for role in roots]
    while pending:
        role = pending.pop()
        if role in seen:
            continue
        seen.add(role)
        pending.extend(parents.get(role, ()))
    return seen


def _revision_key(root: Path) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
            env=env,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--", "specs/prod/us"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env=env,
        ).stdout
        if not dirty:
            return head
        signature = hashlib.sha256(dirty.encode("utf-8"))
        base = root / "specs" / "prod" / "us"
        for path in sorted(
            [*base.rglob("*.yml"), *base.rglob("*.yaml")],
            key=lambda item: item.as_posix(),
        ):
            try:
                info = path.stat()
            except OSError:
                continue
            signature.update(
                f"{path.relative_to(root)}:{info.st_mtime_ns}:{info.st_size}".encode("utf-8")
            )
        return f"{head}:dirty:{signature.hexdigest()[:16]}"
    except (OSError, subprocess.SubprocessError):
        signature = hashlib.sha256()
        base = root / "specs" / "prod" / "us"
        for path in sorted(
            [*base.rglob("*.yml"), *base.rglob("*.yaml")],
            key=lambda item: item.as_posix(),
        ):
            try:
                info = path.stat()
            except OSError:
                continue
            signature.update(
                f"{path.relative_to(root)}:{info.st_mtime_ns}:{info.st_size}".encode("utf-8")
            )
        return f"filesystem:{signature.hexdigest()}"
