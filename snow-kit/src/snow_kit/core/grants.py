"""Snowflake grant normalization and write preflight helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .sql import normalize_object_name

_OWNERSHIP_PRIVS = {"OWNERSHIP", "ALL", "ALL PRIVILEGES"}
_OP_PRIVILEGES = {
    "INSERT": "INSERT",
    "UPDATE": "UPDATE",
    "DELETE": "DELETE",
    "MERGE": "INSERT",
    "TRUNCATE": "DELETE",
    "CREATE TABLE": "CREATE TABLE",
    "CREATE VIEW": "CREATE VIEW",
    "CREATE STAGE": "CREATE STAGE",
    "CREATE FILE FORMAT": "CREATE FILE FORMAT",
    "CREATE SEQUENCE": "CREATE SEQUENCE",
    "CREATE FUNCTION": "CREATE FUNCTION",
    "CREATE PIPE": "CREATE PIPE",
    "CREATE SCHEMA": "CREATE SCHEMA",
    "DROP TABLE": "OWNERSHIP",
}


@dataclass(frozen=True)
class Grant:
    privilege: str
    granted_on: str
    name: str
    granted_to: str = ""
    grantee_name: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Grant":
        upper = {str(k).upper(): v for k, v in row.items()}
        return cls(
            privilege=str(upper.get("PRIVILEGE", "")).upper(),
            granted_on=str(upper.get("GRANTED_ON", "")).upper(),
            name=str(upper.get("NAME", "")).upper(),
            granted_to=str(upper.get("GRANTED_TO", "")).upper(),
            grantee_name=str(upper.get("GRANTEE_NAME", "")).upper(),
        )


def normalize_grants(rows: list[dict[str, Any]]) -> list[Grant]:
    return [Grant.from_row(row) for row in rows]


def required_privilege(operation: str) -> str:
    op = operation.strip().upper()
    return _OP_PRIVILEGES.get(op, op)


def has_grant(grants: list[Grant], *, object_name: str, operation: str) -> tuple[bool, list[Grant]]:
    """Return whether grants include the privilege required for object/operation."""
    op = operation.strip().upper()
    if op == "MERGE":
        insert_ok, insert_matches = _has_single_grant(grants, object_name=object_name, operation="INSERT")
        update_ok, update_matches = _has_single_grant(grants, object_name=object_name, operation="UPDATE")
        return insert_ok and update_ok, insert_matches + update_matches
    return _has_single_grant(grants, object_name=object_name, operation=operation)


def _has_single_grant(grants: list[Grant], *, object_name: str, operation: str) -> tuple[bool, list[Grant]]:
    required = required_privilege(operation)
    normalized = normalize_object_name(object_name)
    candidates = {normalized}
    parts = normalized.split(".")
    if len(parts) >= 2 and required.startswith("CREATE"):
        candidates.add(".".join(parts[:2]))
    matches: list[Grant] = []
    for grant in grants:
        grant_name = _normalize_grant_name(grant.name)
        if grant_name not in candidates:
            continue
        if grant.privilege == required or grant.privilege in _OWNERSHIP_PRIVS:
            matches.append(grant)
    return bool(matches), matches


def _normalize_grant_name(name: str) -> str:
    value = name.strip()
    if not value:
        return ""
    try:
        return normalize_object_name(value)
    except ValueError:
        return value.upper()


def grant_dicts(grants: list[Grant]) -> list[dict[str, str]]:
    return [
        {
            "privilege": grant.privilege,
            "granted_on": grant.granted_on,
            "name": grant.name,
            "granted_to": grant.granted_to,
            "grantee_name": grant.grantee_name,
        }
        for grant in grants
    ]
