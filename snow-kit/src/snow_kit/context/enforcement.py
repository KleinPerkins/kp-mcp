"""Warning-first analytical context policy shared by query and catalog tools."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import sqlglot
from sqlglot import expressions

from snow_kit.context.source import build_context_source
from snow_kit.core.config import SnowKitConfig
from snow_kit.core.errors import Permission, Validation
from snow_kit.core.sql import statement_type

_CONTEXT_WARNING = (
    "Analytical SQL references tables without approved context. Call context.search "
    "first and pass its document_id and revision in context_refs."
)
_DISCOVERY_WARNING = (
    "Unscoped catalog discovery can replace missing business context with guesses. "
    "Call context.search first, then scope metadata discovery to the known database/schema."
)


def query_context_warnings(
    sql: str,
    references: Iterable[Any],
    *,
    config: SnowKitConfig | None = None,
) -> list[str]:
    """Validate references and enforce configured context-first query behavior."""
    resolved = config or SnowKitConfig.from_env()
    refs = [
        (str(reference.document_id), str(reference.revision))
        for reference in references
    ]
    source = build_context_source(resolved)
    if refs:
        if source is None:
            raise Validation(
                "context_refs were supplied but no authoritative source is configured",
                op="query.context_refs",
            )
        source.validate_references(refs)

    if resolved.context_mode == "off" or not _is_table_bearing_analytics(sql) or refs:
        return []
    if resolved.context_mode == "strict":
        raise Permission(
            _CONTEXT_WARNING
            + " Strict context-first mode blocks this query until a valid reference is supplied.",
            op="query.context",
        )
    warning = _CONTEXT_WARNING
    if source is None:
        warning += " The source is not configured; run `snow-kit setup --context-repo <checkout>`."
    return [warning]


def catalog_scope_warnings(
    *,
    scoped: bool,
    op: str,
    config: SnowKitConfig | None = None,
) -> list[str]:
    """Warn or reject metadata discovery that lacks database/schema scope."""
    if scoped:
        return []
    resolved = config or SnowKitConfig.from_env()
    if resolved.context_mode == "off":
        return []
    if resolved.context_mode == "strict":
        raise Permission(
            _DISCOVERY_WARNING + " Strict context-first mode blocks this request.",
            op=op,
        )
    return [_DISCOVERY_WARNING]


def _is_table_bearing_analytics(sql: str) -> bool:
    stype = statement_type(sql)
    if stype in {"EMPTY", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "USE"}:
        return False
    try:
        parsed = sqlglot.parse_one(sql, read="snowflake")
    except sqlglot.errors.ParseError:
        # The normal SQL guard/connector owns syntax validation. Do not turn a
        # parser disagreement into a context-policy bypass for obvious FROM/JOIN.
        upper = sql.upper()
        return " FROM " in f" {upper} " or " JOIN " in f" {upper} "
    return any(True for _table in parsed.find_all(expressions.Table))
