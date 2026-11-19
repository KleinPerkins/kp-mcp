"""Core functions for Snowflake catalog operations."""
from __future__ import annotations

import json
import re
from typing import Any

from snow_kit.context.enforcement import catalog_scope_warnings
from snow_kit.core.config import SnowKitConfig
from snow_kit.core.connection import SnowflakeSession, default_session
from snow_kit.core.grants import grant_dicts, has_grant, normalize_grants, required_privilege
from snow_kit.core.normalize import Meta
from snow_kit.core.spec_index import SpecIndex
from snow_kit.core.sql import (
    identifier_value,
    quote_sql_string,
    sanitize_identifier,
    sanitize_like_pattern,
    split_identifier,
)

from .models import (
    CatalogCheckWriteAccessData,
    CatalogCheckWriteAccessInput,
    CatalogCheckWriteAccessOutput,
    CatalogDescribeTableInput,
    CatalogDescribeTableOutput,
    CatalogGetTableStatsData,
    CatalogGetTableStatsInput,
    CatalogGetTableStatsOutput,
    CatalogListTablesInput,
    CatalogListTablesOutput,
    CatalogPreviewTableInput,
    CatalogPreviewTableOutput,
    CatalogRowsData,
    CatalogSearchColumnsInput,
    CatalogSearchColumnsOutput,
)

_SHOW_ROW_CAP = 10_000
_LAST_ALTERED_WARNING = (
    "LAST_ALTERED is unavailable from SHOW TABLES and is returned as null "
    "to preserve the catalog.get_table_stats output schema."
)


def catalog_list_tables(inp: CatalogListTablesInput, *, session: SnowflakeSession | Any = None) -> CatalogListTablesOutput:
    """List tables in a database/schema with optional LIKE pattern."""
    session = session or default_session()
    config = _session_config(session)
    scope_warnings = catalog_scope_warnings(
        scoped=bool(inp.database or inp.schema_name or config.database or config.schema),
        op="catalog.list_tables",
        config=config,
    )
    query = "SHOW TABLES"
    if inp.pattern:
        query += f" LIKE {quote_sql_string(sanitize_like_pattern(inp.pattern))}"
    if inp.database and inp.schema_name:
        query += f" IN SCHEMA {sanitize_identifier(inp.database)}.{sanitize_identifier(inp.schema_name)}"
    elif inp.database:
        query += f" IN DATABASE {sanitize_identifier(inp.database)}"
    elif inp.schema_name:
        query += f" IN SCHEMA {sanitize_identifier(inp.schema_name)}"
    query += f" LIMIT {inp.limit}"
    result = session.execute(query, op="catalog.list_tables", max_rows=inp.limit)
    return _rows_output(
        CatalogListTablesOutput,
        "catalog.list_tables",
        result,
        extra_warnings=scope_warnings,
    )


def catalog_describe_table(inp: CatalogDescribeTableInput, *, session: SnowflakeSession | Any = None) -> CatalogDescribeTableOutput:
    """Describe a Snowflake table's columns and metadata."""
    session = session or default_session()
    table_name = sanitize_identifier(inp.table_name)
    result = session.execute("DESCRIBE TABLE IDENTIFIER(%s)", (table_name,), op="catalog.describe_table")
    return _rows_output(CatalogDescribeTableOutput, "catalog.describe_table", result)


def catalog_preview_table(inp: CatalogPreviewTableInput, *, session: SnowflakeSession | Any = None) -> CatalogPreviewTableOutput:
    """Preview sample rows from a Snowflake table."""
    session = session or default_session()
    table_name = sanitize_identifier(inp.table_name)
    result = session.execute(
        f"SELECT * FROM IDENTIFIER(%s) LIMIT {inp.limit}",
        (table_name,),
        op="catalog.preview_table",
        max_rows=inp.limit,
    )
    return _rows_output(CatalogPreviewTableOutput, "catalog.preview_table", result)


def catalog_search_columns(inp: CatalogSearchColumnsInput, *, session: SnowflakeSession | Any = None) -> CatalogSearchColumnsOutput:
    """Search bounded SHOW COLUMNS metadata and flag its 10,000-row cap."""
    session = session or default_session()
    config = _session_config(session)
    scope_warnings = catalog_scope_warnings(
        scoped=bool(inp.database or inp.schema_name or config.database or config.schema),
        op="catalog.search_columns",
        config=config,
    )
    pattern = sanitize_like_pattern(inp.column_name)
    query = f"SHOW COLUMNS LIKE {quote_sql_string(pattern)} {_catalog_scope(inp.database, inp.schema_name, session)}"
    result = session.execute(query, op="catalog.search_columns", max_rows=inp.limit)
    matcher = _like_matcher(pattern)
    rows = [
        normalized
        for row in result.rows
        if (normalized := _normalize_column_row(row))
        and matcher.fullmatch(str(normalized["COLUMN_NAME"]))
    ]
    show_cap_reached = len(result.rows) >= _SHOW_ROW_CAP
    warnings = list(scope_warnings)
    if show_cap_reached:
        warnings.append(
            "Snowflake SHOW COLUMNS returned its 10,000-row maximum; "
            "results may be incomplete even though no additional row was observable."
        )
    return _rows_output(
        CatalogSearchColumnsOutput,
        "catalog.search_columns",
        result,
        rows=rows,
        truncated=result.truncated or show_cap_reached,
        extra_warnings=warnings,
    )


def catalog_get_table_stats(inp: CatalogGetTableStatsInput, *, session: SnowflakeSession | Any = None) -> CatalogGetTableStatsOutput:
    """Get bounded SHOW TABLES metadata; LAST_ALTERED remains null because SHOW omits it."""
    session = session or default_session()
    parts = split_identifier(inp.table_name)
    if len(parts) > 3:
        raise ValueError("table_name must have at most database, schema, and table parts")
    table_part = parts[-1]
    expected_name = identifier_value(table_part)
    database_wide = len(parts) == 1 and not _session_config(session).schema
    lookup_limit = _SHOW_ROW_CAP if database_wide else 1
    query = (
        f"SHOW TABLES {_table_scope(parts, session)} "
        f"STARTS WITH {quote_sql_string(expected_name)} LIMIT {lookup_limit}"
    )
    result = session.execute(query, op="catalog.get_table_stats", max_rows=lookup_limit)
    exact_rows = sorted(
        (
            row
            for row in result.rows
            if _identifier_matches(_row_value(row, "name", "table_name"), table_part)
        ),
        key=_table_row_sort_key,
    )
    stats = _normalize_table_stats(exact_rows[0]) if exact_rows else None
    if stats and stats.get("BYTES") is not None:
        stats["SIZE_READABLE"] = _human_size(float(stats["BYTES"]))
    warnings = [_LAST_ALTERED_WARNING] if stats else []
    if database_wide and (result.truncated or len(result.rows) >= _SHOW_ROW_CAP):
        warnings.append(
            "The database-wide SHOW TABLES lookup reached its bounded row cap; "
            "an exact match in a later schema may be unavailable."
        )
    if database_wide and len(exact_rows) > 1:
        warnings.append(
            "The unqualified table name matched multiple schemas; "
            "returned the lexicographically first database/schema match."
        )
    return CatalogGetTableStatsOutput(
        data=CatalogGetTableStatsData(stats=stats, execution_time_ms=result.execution_time_ms),
        warnings=warnings,
        meta=Meta(op="catalog.get_table_stats", latency_ms=result.execution_time_ms),
    )


def catalog_check_write_access(inp: CatalogCheckWriteAccessInput, *, session: SnowflakeSession | Any = None) -> CatalogCheckWriteAccessOutput:
    """Inspect current-role Snowflake grants and optional spec context for write access."""
    session = session or default_session()
    config: SnowKitConfig = getattr(session, "config", SnowKitConfig.from_env())
    context = session.current_context()
    active_role = str(context.get("ROLE") or "") or None
    grants = normalize_grants(session.show_current_role_grants())
    has_access, matches = has_grant(grants, object_name=inp.object_name, operation=inp.operation)
    spec = SpecIndex(config.spec_path).explain(
        object_name=inp.object_name,
        operation=inp.operation,
        role=inp.role,
        email=inp.email,
    )
    warnings = list(spec.warnings)
    if not spec.available:
        warnings.append("snowflake-permission-specs unavailable; returned Snowflake grants only.")
    return CatalogCheckWriteAccessOutput(
        data=CatalogCheckWriteAccessData(
            object_name=inp.object_name,
            operation=inp.operation.upper(),
            required_privilege=required_privilege(inp.operation),
            active_role=active_role,
            has_snowflake_grant=has_access,
            matching_grants=grant_dicts(matches),
            live_grants_decisive=True,
            spec_available=spec.available,
            spec_revision=spec.revision,
            spec_matches=[match.__dict__ for match in spec.matched],
            roles_for_email=spec.roles_for_email,
        ),
        warnings=warnings,
        meta=Meta(op="catalog.check_write_access"),
    )


def _rows_output(
    model: Any,
    op: str,
    result: Any,
    *,
    rows: list[dict[str, Any]] | None = None,
    truncated: bool | None = None,
    extra_warnings: list[str] | None = None,
) -> Any:
    output_rows = result.rows if rows is None else rows
    warnings = []
    if result.truncated:
        warnings.append("Results truncated to the requested or configured row cap.")
    warnings.extend(extra_warnings or [])
    output_truncated = result.truncated if truncated is None else truncated
    return model(
        data=CatalogRowsData(
            rows=output_rows,
            count=len(output_rows),
            truncated=output_truncated,
            execution_time_ms=result.execution_time_ms,
        ),
        warnings=warnings,
        meta=Meta(op=op, latency_ms=result.execution_time_ms),
    )


def _session_config(session: Any) -> SnowKitConfig:
    config = getattr(session, "config", None)
    return config if config is not None else SnowKitConfig.from_env()


def _one_identifier(value: str, *, field: str) -> str:
    sanitized = sanitize_identifier(value)
    if len(split_identifier(sanitized)) != 1:
        raise ValueError(f"{field} must be a single SQL identifier")
    return sanitized


def _catalog_scope(database: str | None, schema: str | None, session: Any) -> str:
    config = _session_config(session)
    raw_database = database or config.database
    if not raw_database:
        if schema:
            return f"IN SCHEMA {_one_identifier(schema, field='schema')}"
        return ""
    selected_database = _one_identifier(raw_database, field="database")
    if schema:
        selected_schema = _one_identifier(schema, field="schema")
        return f"IN SCHEMA {selected_database}.{selected_schema}"
    return f"IN DATABASE {selected_database}"


def _table_scope(parts: list[str], session: Any) -> str:
    config = _session_config(session)
    if len(parts) == 3:
        database, schema = parts[:2]
        return f"IN SCHEMA {database}.{schema}"
    if len(parts) == 2:
        if config.database:
            database = _one_identifier(config.database, field="database")
            return f"IN SCHEMA {database}.{parts[0]}"
        return f"IN SCHEMA {parts[0]}"
    if not config.database:
        if config.schema:
            return f"IN SCHEMA {_one_identifier(config.schema, field='schema')}"
        return ""
    database = _one_identifier(config.database, field="database")
    if config.schema:
        schema = _one_identifier(config.schema, field="schema")
        return f"IN SCHEMA {database}.{schema}"
    return f"IN DATABASE {database}"


def _row_value(row: dict[str, Any], *names: str) -> Any:
    folded = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return None


def _identifier_matches(actual: Any, expected_part: str) -> bool:
    if actual is None:
        return False
    expected = identifier_value(expected_part)
    if expected_part.startswith('"'):
        return str(actual) == expected
    return str(actual).upper() == expected


def _table_row_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(_row_value(row, "database_name") or "").casefold(),
        str(_row_value(row, "schema_name") or "").casefold(),
        str(_row_value(row, "name") or "").casefold(),
    )


def _normalize_table_stats(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "DATABASE_NAME": _row_value(row, "database_name", "table_catalog"),
        "SCHEMA_NAME": _row_value(row, "schema_name", "table_schema"),
        "TABLE_NAME": _row_value(row, "name", "table_name"),
        "TABLE_TYPE": _normalize_show_table_type(row),
        "ROW_COUNT": _row_value(row, "rows", "row_count"),
        "BYTES": _row_value(row, "bytes"),
        "CREATED": _row_value(row, "created_on", "created"),
        "LAST_ALTERED": None,
        "CLUSTERING_KEY": _row_value(row, "cluster_by", "clustering_key"),
    }


def _normalize_show_table_type(row: dict[str, Any]) -> Any:
    for flag, table_type in (
        ("is_event", "EVENT TABLE"),
        ("is_dynamic", "DYNAMIC TABLE"),
        ("is_external", "EXTERNAL TABLE"),
        ("is_hybrid", "HYBRID TABLE"),
        ("is_iceberg", "ICEBERG TABLE"),
        ("is_immutable", "IMMUTABLE TABLE"),
    ):
        if _snowflake_flag(_row_value(row, flag)):
            return table_type

    kind = _row_value(row, "kind", "table_type")
    if not isinstance(kind, str):
        return kind
    normalized = kind.strip().upper().replace("_", " ")
    return {
        "TABLE": "BASE TABLE",
        "TEMPORARY": "TEMPORARY TABLE",
        "TRANSIENT": "TRANSIENT TABLE",
    }.get(normalized, normalized)


def _snowflake_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().upper() in {"1", "ON", "TRUE", "Y", "YES"}
    return value == 1


def _normalize_column_row(row: dict[str, Any]) -> dict[str, Any]:
    nullable = _row_value(row, "is_nullable", "null?")
    if isinstance(nullable, bool):
        nullable = "YES" if nullable else "NO"
    elif isinstance(nullable, str):
        nullable = {
            "TRUE": "YES",
            "Y": "YES",
            "YES": "YES",
            "FALSE": "NO",
            "N": "NO",
            "NO": "NO",
        }.get(nullable.strip().upper(), nullable)
    return {
        "DATABASE_NAME": _row_value(row, "database_name", "table_catalog"),
        "SCHEMA_NAME": _row_value(row, "schema_name", "table_schema"),
        "TABLE_NAME": _row_value(row, "table_name"),
        "COLUMN_NAME": _row_value(row, "column_name", "name"),
        "DATA_TYPE": _normalize_show_data_type(_row_value(row, "data_type")),
        "IS_NULLABLE": nullable,
    }


def _normalize_show_data_type(value: Any) -> Any:
    payload = value
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return value
    if not isinstance(payload, dict):
        return value
    type_name = payload.get("type")
    if not isinstance(type_name, str):
        return value
    return {"FIXED": "NUMBER", "REAL": "FLOAT"}.get(type_name.upper(), type_name.upper())


def _like_matcher(pattern: str) -> re.Pattern[str]:
    expression = "".join(
        ".*" if char == "%" else "." if char == "_" else re.escape(char)
        for char in pattern
    )
    return re.compile(expression, re.IGNORECASE | re.DOTALL)


def _human_size(size: float) -> str:
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.2f} GB"
    if size >= 1_000_000:
        return f"{size / 1_000_000:.2f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.2f} KB"
    return f"{size:.0f} B"
