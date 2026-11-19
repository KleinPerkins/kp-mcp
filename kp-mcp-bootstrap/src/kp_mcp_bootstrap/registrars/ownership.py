"""RFC 6901 leaf ownership and three-way reconciliation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

from kp_mcp_bootstrap.errors import ReasonCode

from .contracts import (
    ABSENT_DIGEST,
    OwnedLeafAction,
    digest_value,
    iter_mapping_leaves,
    pointer_unescape,
)
from .native_json import native_number_digest


_ABSENT = object()
_AUTH_ROOTS = {
    "/auth",
    "/oauth",
    "/headers",
    "/env_http_headers",
    "/bearer_token_env_var",
}


def semantic_digest(value: Any) -> str:
    if value is _ABSENT:
        return ABSENT_DIGEST
    native_digest = native_number_digest(value)
    return native_digest if native_digest is not None else digest_value(value)


def _segments(pointer: str) -> tuple[str, ...]:
    return tuple(pointer_unescape(part) for part in pointer[1:].split("/"))


def get_leaf(value: Mapping[str, Any], pointer: str) -> Any:
    current: Any = value
    for segment in _segments(pointer):
        if not isinstance(current, Mapping) or segment not in current:
            return _ABSENT
        current = current[segment]
    return current


def set_leaf(value: MutableMapping[str, Any], pointer: str, desired: Any) -> None:
    segments = _segments(pointer)
    current: MutableMapping[str, Any] = value
    for segment in segments[:-1]:
        if segment not in current:
            child = {}
            current[segment] = child
        else:
            child = current[segment]
        if not isinstance(child, MutableMapping):
            raise ValueError("owned path crosses a non-map")
        current = child
    current[segments[-1]] = copy.deepcopy(desired)


def delete_leaf(value: MutableMapping[str, Any], pointer: str) -> None:
    segments = _segments(pointer)
    current: MutableMapping[str, Any] = value
    for segment in segments[:-1]:
        child = current.get(segment)
        if not isinstance(child, MutableMapping):
            return
        current = child
    current.pop(segments[-1], None)


def _has_non_mapping_ancestor(value: Mapping[str, Any], pointer: str) -> bool:
    """Return whether setting pointer would overwrite an explicit ancestor."""

    current: Any = value
    for segment in _segments(pointer)[:-1]:
        if not isinstance(current, Mapping):
            return True
        if segment not in current:
            return False
        current = current[segment]
        if not isinstance(current, Mapping):
            return True
    return False


def projection_digests(
    entry: Mapping[str, Any], paths: Mapping[str, Any]
) -> dict[str, str]:
    return {path: semantic_digest(get_leaf(entry, path)) for path in sorted(paths)}


def flatten_paths(entry: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(path for path, _value in iter_mapping_leaves(entry) if path)


def _auth_shape_present(entry: Mapping[str, Any]) -> bool:
    return any(get_leaf(entry, root) is not _ABSENT for root in _AUTH_ROOTS)


def _headers_have_case_collision(entry: Mapping[str, Any]) -> bool:
    for root in ("/headers", "/env_http_headers"):
        headers = get_leaf(entry, root)
        if not isinstance(headers, Mapping):
            continue
        seen: dict[str, Any] = {}
        for key, value in headers.items():
            lowered = str(key).lower()
            if lowered in seen and seen[lowered] != value:
                return True
            seen[lowered] = value
    return False


@dataclass(frozen=True, slots=True)
class MergeResult:
    entry: Mapping[str, Any]
    source_projection: Mapping[str, str]
    auth_projection: Mapping[str, str]
    actions: tuple[OwnedLeafAction, ...]
    preserved_paths: tuple[str, ...]
    conflicts: tuple[ReasonCode, ...]


def _merge_projection(
    updated: MutableMapping[str, Any],
    current: Mapping[str, Any],
    desired: Mapping[str, Any],
    base: Mapping[str, str],
    *,
    allow_equal_adoption: bool,
) -> tuple[list[OwnedLeafAction], list[ReasonCode]]:
    actions: list[OwnedLeafAction] = []
    conflicts: list[ReasonCode] = []
    for path in sorted(set(base) | set(desired)):
        current_value = get_leaf(current, path)
        current_digest = semantic_digest(current_value)
        desired_value = desired.get(path, _ABSENT)
        desired_digest = semantic_digest(desired_value)
        if desired_value is not _ABSENT and _has_non_mapping_ancestor(current, path):
            conflicts.append(
                ReasonCode.OWNED_FIELD_DRIFT
                if path in base
                else ReasonCode.OWNER_CONFLICT
            )
            continue
        if path not in base:
            if current_value is not _ABSENT:
                if allow_equal_adoption and current_digest == desired_digest:
                    actions.append(OwnedLeafAction(path, "retain"))
                else:
                    conflicts.append(ReasonCode.OWNER_CONFLICT)
                continue
            if desired_value is _ABSENT:
                continue
            set_leaf(updated, path, desired_value)
            actions.append(OwnedLeafAction(path, "add"))
            continue
        base_digest = base[path]
        if current_digest not in {base_digest, desired_digest}:
            conflicts.append(ReasonCode.OWNED_FIELD_DRIFT)
            continue
        if desired_value is _ABSENT:
            if current_value is not _ABSENT:
                delete_leaf(updated, path)
                actions.append(OwnedLeafAction(path, "remove"))
            else:
                actions.append(OwnedLeafAction(path, "retain"))
        elif current_digest == desired_digest:
            actions.append(OwnedLeafAction(path, "retain"))
        else:
            set_leaf(updated, path, desired_value)
            actions.append(OwnedLeafAction(path, "replace"))
    return actions, conflicts


def reconcile_entry(
    current: Mapping[str, Any] | None,
    desired_source: Mapping[str, Any],
    desired_auth: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    *,
    adoption: bool,
    incompatible_paths: frozenset[str],
    prunable_ancestors: frozenset[str] = frozenset(),
) -> MergeResult:
    """Apply three-way rules without mutating the caller's mapping."""

    original: Mapping[str, Any] = current or {}
    updated: MutableMapping[str, Any] = copy.deepcopy(dict(original))
    source_base: Mapping[str, str] = {}
    auth_base: Mapping[str, str] = {}
    if receipt:
        source_base = receipt.get("source_projection", {}).get("paths", {})
        auth_base = receipt.get("auth_projection", {}).get("paths", {})
    conflicts: list[ReasonCode] = []
    if set(source_base) & set(auth_base):
        conflicts.append(ReasonCode.OWNER_CONFLICT)
    if set(desired_source) & set(desired_auth):
        conflicts.append(ReasonCode.AUTH_BINDING_CONFLICT)
    if _headers_have_case_collision(original):
        conflicts.append(ReasonCode.AUTH_BINDING_CONFLICT)
    actions, source_conflicts = _merge_projection(
        updated,
        original,
        desired_source,
        source_base,
        allow_equal_adoption=adoption or receipt is None,
    )
    auth_actions, auth_conflicts = _merge_projection(
        updated,
        original,
        desired_auth,
        auth_base,
        allow_equal_adoption=adoption or receipt is None,
    )
    actions.extend(auth_actions)
    conflicts.extend(source_conflicts)
    conflicts.extend(auth_conflicts)
    for path in sorted(prunable_ancestors, key=lambda item: item.count("/"), reverse=True):
        value = get_leaf(updated, path)
        if isinstance(value, Mapping) and not value:
            delete_leaf(updated, path)
    owned = set(source_base) | set(auth_base) | set(desired_source) | set(desired_auth)
    original_leaves = flatten_paths(original)
    for path in incompatible_paths:
        if path.endswith("/*"):
            prefix = path[:-1]
            collisions = {
                leaf for leaf in original_leaves if leaf.startswith(prefix)
            } - owned
            if collisions:
                conflicts.append(ReasonCode.POLICY_CONFLICT)
        elif path not in owned and get_leaf(original, path) is not _ABSENT:
            conflicts.append(ReasonCode.POLICY_CONFLICT)
    if _auth_shape_present(original):
        known_auth = set(auth_base) | set(desired_auth)
        auth_leaves = {
            path
            for path in flatten_paths(original)
            if any(path == root or path.startswith(root + "/") for root in _AUTH_ROOTS)
            and not (
                path in _AUTH_ROOTS
                and isinstance(get_leaf(original, path), Mapping)
                and not get_leaf(original, path)
            )
        }
        if auth_leaves - known_auth:
            conflicts.append(ReasonCode.EXISTING_AUTH_MATERIAL)
    preserved = tuple(sorted(flatten_paths(original) - owned))
    source_projection = {
        path: semantic_digest(get_leaf(updated, path)) for path in sorted(desired_source)
    }
    auth_projection = {
        path: semantic_digest(get_leaf(updated, path)) for path in sorted(desired_auth)
    }
    return MergeResult(
        entry=updated,
        source_projection=source_projection,
        auth_projection=auth_projection,
        actions=tuple(sorted(actions, key=lambda item: (item.path, item.action))),
        preserved_paths=preserved,
        conflicts=tuple(dict.fromkeys(conflicts)),
    )


def can_remove_whole_entry(
    current: Mapping[str, Any], receipt: Mapping[str, Any]
) -> tuple[bool, tuple[ReasonCode, ...]]:
    source = receipt.get("source_projection", {}).get("paths", {})
    auth = receipt.get("auth_projection", {}).get("paths", {})
    owned = set(source) | set(auth)
    current_paths = flatten_paths(current)
    if current_paths - owned:
        return False, (ReasonCode.REMOVAL_CONFLICT,)
    for path, expected in {**source, **auth}.items():
        if semantic_digest(get_leaf(current, path)) != expected:
            return False, (ReasonCode.OWNED_FIELD_DRIFT,)
    return True, ()
