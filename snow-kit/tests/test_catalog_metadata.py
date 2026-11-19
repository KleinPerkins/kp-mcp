"""Focused coverage for bounded SHOW-based catalog metadata paths."""
from __future__ import annotations

from typing import Any

import pytest

from snow_kit.core.config import SnowKitConfig
from snow_kit.core.connection import QueryResult
from snow_kit.core.errors import Timeout
from snow_kit.core.sql import quote_sql_string, sanitize_like_pattern
from snow_kit.services.catalog.core import (
    catalog_get_table_stats,
    catalog_list_tables,
    catalog_search_columns,
)
from snow_kit.services.catalog.models import (
    CatalogGetTableStatsInput,
    CatalogListTablesInput,
    CatalogSearchColumnsInput,
)


LIVE_SHOW_TABLE_ROW: dict[str, Any] = {
    "created_on": "2026-01-01 00:00:00+00:00",
    "name": "EMP",
    "database_name": "EXAMPLE_DB",
    "schema_name": "PUBLIC",
    "kind": "TABLE",
    "rows": 12,
    "bytes": 2_000_000,
    "cluster_by": "LINEAR(ID)",
    "is_dynamic": "N",
    "is_event": "N",
    "is_external": "N",
    "is_hybrid": "N",
    "is_iceberg": "N",
    "is_immutable": "N",
}

LIVE_SHOW_COLUMN_ROW: dict[str, Any] = {
    "table_name": "EMP",
    "schema_name": "PUBLIC",
    "column_name": "EMPNAME",
    "data_type": '{"type":"TEXT","length":100,"byteLength":100,"nullable":true,"fixed":false}',
    "null?": True,
    "kind": "COLUMN",
    "database_name": "EXAMPLE_DB",
}

LAST_ALTERED_WARNING = (
    "LAST_ALTERED is unavailable from SHOW TABLES and is returned as null "
    "to preserve the catalog.get_table_stats output schema."
)
SHOW_COLUMNS_CAP_WARNING = (
    "Snowflake SHOW COLUMNS returned its 10,000-row maximum; "
    "results may be incomplete even though no additional row was observable."
)


class MetadataSession:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        database: str = "EXAMPLE_DB",
        schema: str | None = None,
        truncated: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.config = SnowKitConfig(database=database, schema=schema)
        self.rows = rows or []
        self.truncated = truncated
        self.error = error
        self.calls: list[tuple[str, tuple[Any, ...], str, int | None]] = []

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | list[Any] | None = None,
        *,
        op: str,
        max_rows: int | None = None,
    ) -> QueryResult:
        self.calls.append((sql, tuple(params or ()), op, max_rows))
        if self.error:
            raise self.error
        return QueryResult(
            rows=self.rows,
            columns=list(self.rows[0]) if self.rows else [],
            row_count=len(self.rows),
            truncated=self.truncated,
            execution_time_ms=2.5,
        )


def test_quote_sql_string_escapes_snowflake_backslashes_and_apostrophes() -> None:
    assert quote_sql_string("O'Brien\\Path") == "'O''Brien\\\\Path'"


def test_sanitize_like_pattern_accepts_quoted_identifier_characters() -> None:
    assert sanitize_like_pattern("O'Brien\\Path.\"Column\"") == "O'Brien\\Path.\"Column\""
    with pytest.raises(ValueError, match="Invalid LIKE pattern"):
        sanitize_like_pattern("EMP\nNAME")


def test_list_tables_uses_safe_literal_quoting_for_expanded_patterns() -> None:
    session = MetadataSession()

    catalog_list_tables(
        CatalogListTablesInput(pattern="O'Brien\\Path%"),
        session=session,
    )

    assert session.calls[0][0] == (
        "SHOW TABLES LIKE 'O''Brien\\\\Path%' LIMIT 100"
    )


def test_get_table_stats_uses_bounded_show_and_preserves_contract() -> None:
    session = MetadataSession([LIVE_SHOW_TABLE_ROW])

    out = catalog_get_table_stats(
        CatalogGetTableStatsInput(table_name="EXAMPLE_DB.PUBLIC.EMP"),
        session=session,
    )

    sql, params, op, max_rows = session.calls[0]
    assert sql == "SHOW TABLES IN SCHEMA EXAMPLE_DB.PUBLIC STARTS WITH 'EMP' LIMIT 1"
    assert "INFORMATION_SCHEMA" not in sql
    assert params == ()
    assert (op, max_rows) == ("catalog.get_table_stats", 1)
    assert out.data.stats == {
        "DATABASE_NAME": "EXAMPLE_DB",
        "SCHEMA_NAME": "PUBLIC",
        "TABLE_NAME": "EMP",
        "TABLE_TYPE": "BASE TABLE",
        "ROW_COUNT": 12,
        "BYTES": 2_000_000,
        "CREATED": "2026-01-01 00:00:00+00:00",
        "LAST_ALTERED": None,
        "CLUSTERING_KEY": "LINEAR(ID)",
        "SIZE_READABLE": "2.00 MB",
    }
    assert out.warnings == [LAST_ALTERED_WARNING]


@pytest.mark.parametrize(
    ("table_name", "database", "schema", "expected_scope"),
    [
        ("EXAMPLE_DB.PUBLIC.EMP", "IGNORED", None, "EXAMPLE_DB.PUBLIC"),
        ("PUBLIC.EMP", "EXAMPLE_DB", None, "EXAMPLE_DB.PUBLIC"),
        ("EMP", "EXAMPLE_DB", "CURATED", "EXAMPLE_DB.CURATED"),
    ],
)
def test_get_table_stats_scopes_qualified_and_configured_schema_names(
    table_name: str,
    database: str,
    schema: str | None,
    expected_scope: str,
) -> None:
    session = MetadataSession([LIVE_SHOW_TABLE_ROW], database=database, schema=schema)

    catalog_get_table_stats(CatalogGetTableStatsInput(table_name=table_name), session=session)

    assert session.calls[0][0] == (
        f"SHOW TABLES IN SCHEMA {expected_scope} STARTS WITH 'EMP' LIMIT 1"
    )
    assert session.calls[0][3] == 1


def test_get_table_stats_escapes_complex_quoted_identifier_literal() -> None:
    table_name = "\"Prod.Db\".\"Schema%_Part\".\"O'Brien\\Path%_\"\"dot\""
    row = {
        **LIVE_SHOW_TABLE_ROW,
        "name": "O'Brien\\Path%_\"dot",
        "database_name": "Prod.Db",
        "schema_name": "Schema%_Part",
    }
    session = MetadataSession([row])

    out = catalog_get_table_stats(CatalogGetTableStatsInput(table_name=table_name), session=session)

    assert session.calls[0][0] == (
        'SHOW TABLES IN SCHEMA "Prod.Db"."Schema%_Part" '
        "STARTS WITH 'O''Brien\\\\Path%_\"dot' LIMIT 1"
    )
    assert out.data.stats and out.data.stats["TABLE_NAME"] == "O'Brien\\Path%_\"dot"


def test_get_table_stats_database_lookup_does_not_lose_later_exact_match() -> None:
    session = MetadataSession(
        [
            {
                **LIVE_SHOW_TABLE_ROW,
                "name": "EMP_ARCHIVE",
                "schema_name": "A_EARLIER_SCHEMA",
            },
            {
                **LIVE_SHOW_TABLE_ROW,
                "name": "EMP",
                "schema_name": "Z_LATER_SCHEMA",
            },
        ],
    )

    out = catalog_get_table_stats(CatalogGetTableStatsInput(table_name="EMP"), session=session)

    assert session.calls[0][0] == (
        "SHOW TABLES IN DATABASE EXAMPLE_DB STARTS WITH 'EMP' LIMIT 10000"
    )
    assert session.calls[0][3] == 10_000
    assert out.data.stats and out.data.stats["SCHEMA_NAME"] == "Z_LATER_SCHEMA"


def test_get_table_stats_database_lookup_selects_duplicate_names_deterministically() -> None:
    session = MetadataSession(
        [
            {**LIVE_SHOW_TABLE_ROW, "schema_name": "Z_LAST"},
            {**LIVE_SHOW_TABLE_ROW, "schema_name": "A_FIRST"},
        ],
    )

    out = catalog_get_table_stats(CatalogGetTableStatsInput(table_name="EMP"), session=session)

    assert out.data.stats and out.data.stats["SCHEMA_NAME"] == "A_FIRST"
    assert any("matched multiple schemas" in warning for warning in out.warnings)


@pytest.mark.parametrize("rows", [[], [{"name": "EMP_ARCHIVE", "bytes": 1}]])
def test_get_table_stats_returns_none_for_empty_or_prefix_only_results(
    rows: list[dict[str, Any]],
) -> None:
    out = catalog_get_table_stats(
        CatalogGetTableStatsInput(table_name="EMP"),
        session=MetadataSession(rows),
    )

    assert out.data.stats is None
    assert out.warnings == []


def test_get_table_stats_marks_database_lookup_cap_as_potentially_incomplete() -> None:
    rows = [
        {**LIVE_SHOW_TABLE_ROW, "name": f"EMP_{index:05d}"}
        for index in range(10_000)
    ]

    out = catalog_get_table_stats(
        CatalogGetTableStatsInput(table_name="EMP"),
        session=MetadataSession(rows),
    )

    assert out.data.stats is None
    assert any("exact match in a later schema may be unavailable" in warning for warning in out.warnings)


@pytest.mark.parametrize(
    ("changes", "expected_type"),
    [
        ({"kind": "TABLE"}, "BASE TABLE"),
        ({"kind": "TRANSIENT"}, "TRANSIENT TABLE"),
        ({"kind": "TEMPORARY"}, "TEMPORARY TABLE"),
        ({"is_external": "Y"}, "EXTERNAL TABLE"),
        ({"is_event": "YES"}, "EVENT TABLE"),
        ({"is_dynamic": True}, "DYNAMIC TABLE"),
        ({"is_hybrid": "Y"}, "HYBRID TABLE"),
        ({"is_iceberg": "Y"}, "ICEBERG TABLE"),
        ({"is_immutable": "Y"}, "IMMUTABLE TABLE"),
    ],
)
def test_get_table_stats_maps_show_kind_and_flags(
    changes: dict[str, Any],
    expected_type: str,
) -> None:
    row = {**LIVE_SHOW_TABLE_ROW, **changes}

    out = catalog_get_table_stats(
        CatalogGetTableStatsInput(table_name="EXAMPLE_DB.PUBLIC.EMP"),
        session=MetadataSession([row]),
    )

    assert out.data.stats and out.data.stats["TABLE_TYPE"] == expected_type


def test_get_table_stats_rejects_unsafe_identifier_before_query() -> None:
    session = MetadataSession()

    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        catalog_get_table_stats(
            CatalogGetTableStatsInput(table_name="EMP; DROP TABLE USERS"),
            session=session,
        )

    assert session.calls == []


def test_search_columns_uses_live_show_shape_and_normalizes_boolean_nullable() -> None:
    session = MetadataSession(
        [
            LIVE_SHOW_COLUMN_ROW,
            {
                **LIVE_SHOW_COLUMN_ROW,
                "column_name": "OTHER",
                "null?": False,
            },
        ]
    )

    out = catalog_search_columns(
        CatalogSearchColumnsInput(column_name="EMPNAME"),
        session=session,
    )

    sql, params, op, max_rows = session.calls[0]
    assert sql == "SHOW COLUMNS LIKE 'EMPNAME' IN DATABASE EXAMPLE_DB"
    assert "INFORMATION_SCHEMA" not in sql
    assert params == ()
    assert (op, max_rows) == ("catalog.search_columns", 1_000)
    assert out.data.rows == [
        {
            "DATABASE_NAME": "EXAMPLE_DB",
            "SCHEMA_NAME": "PUBLIC",
            "TABLE_NAME": "EMP",
            "COLUMN_NAME": "EMPNAME",
            "DATA_TYPE": "TEXT",
            "IS_NULLABLE": "YES",
        }
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Y", "YES"),
        ("YES", "YES"),
        ("true", "YES"),
        ("N", "NO"),
        ("NO", "NO"),
        ("false", "NO"),
        (True, "YES"),
        (False, "NO"),
    ],
)
def test_search_columns_normalizes_supported_nullable_shapes(
    source: str | bool,
    expected: str,
) -> None:
    row = {**LIVE_SHOW_COLUMN_ROW, "null?": source}

    out = catalog_search_columns(
        CatalogSearchColumnsInput(column_name="EMPNAME"),
        session=MetadataSession([row]),
    )

    assert out.data.rows[0]["IS_NULLABLE"] == expected


def test_search_columns_supports_case_insensitive_wildcards() -> None:
    session = MetadataSession(
        [
            {**LIVE_SHOW_COLUMN_ROW, "column_name": "EMP_NAME"},
            {**LIVE_SHOW_COLUMN_ROW, "column_name": "employee_name"},
            {**LIVE_SHOW_COLUMN_ROW, "column_name": "EMP_LONG_NAME"},
            {**LIVE_SHOW_COLUMN_ROW, "column_name": "OTHER"},
        ]
    )

    out = catalog_search_columns(
        CatalogSearchColumnsInput(column_name="EMP%_NAME"),
        session=session,
    )

    assert [row["COLUMN_NAME"] for row in out.data.rows] == [
        "EMP_NAME",
        "employee_name",
        "EMP_LONG_NAME",
    ]


def test_search_columns_escapes_punctuation_pattern_without_binding() -> None:
    pattern = "O'Brien\\Path.\"Column\""
    row = {**LIVE_SHOW_COLUMN_ROW, "column_name": pattern}
    session = MetadataSession([row])

    out = catalog_search_columns(
        CatalogSearchColumnsInput(column_name=pattern),
        session=session,
    )

    assert session.calls[0][0] == (
        "SHOW COLUMNS LIKE 'O''Brien\\\\Path.\"Column\"' IN DATABASE EXAMPLE_DB"
    )
    assert out.data.rows[0]["COLUMN_NAME"] == pattern


@pytest.mark.parametrize(
    ("database", "schema", "expected_scope"),
    [
        (None, None, "IN DATABASE EXAMPLE_DB"),
        ("ANALYTICS", None, "IN DATABASE ANALYTICS"),
        (None, "PUBLIC", "IN SCHEMA EXAMPLE_DB.PUBLIC"),
        ("ANALYTICS", "PUBLIC", "IN SCHEMA ANALYTICS.PUBLIC"),
    ],
)
def test_search_columns_retains_optional_scopes(
    database: str | None,
    schema: str | None,
    expected_scope: str,
) -> None:
    session = MetadataSession([LIVE_SHOW_COLUMN_ROW])

    catalog_search_columns(
        CatalogSearchColumnsInput(
            column_name="EMPNAME",
            database=database,
            schema=schema,
            limit=25,
        ),
        session=session,
    )

    assert session.calls[0][0] == f"SHOW COLUMNS LIKE 'EMPNAME' {expected_scope}"
    assert session.calls[0][3] == 25


def test_search_columns_preserves_requested_limit_truncation() -> None:
    out = catalog_search_columns(
        CatalogSearchColumnsInput(column_name="EMP%", limit=1),
        session=MetadataSession(
            [{**LIVE_SHOW_COLUMN_ROW, "column_name": "EMP_ID"}],
            truncated=True,
        ),
    )

    assert out.data.truncated is True
    assert out.warnings == ["Results truncated to the requested or configured row cap."]


def test_search_columns_marks_silent_show_cap_as_potentially_truncated() -> None:
    rows = [
        {**LIVE_SHOW_COLUMN_ROW, "column_name": f"COL_{index:05d}"}
        for index in range(10_000)
    ]

    out = catalog_search_columns(
        CatalogSearchColumnsInput(column_name="COL%", limit=10_000),
        session=MetadataSession(rows),
    )

    assert out.data.count == 10_000
    assert out.data.truncated is True
    assert out.warnings == [SHOW_COLUMNS_CAP_WARNING]


def test_search_columns_empty_results_are_complete() -> None:
    out = catalog_search_columns(
        CatalogSearchColumnsInput(column_name="MISSING%"),
        session=MetadataSession(),
    )

    assert out.data.rows == []
    assert out.data.count == 0
    assert out.data.truncated is False
    assert out.warnings == []


def test_search_columns_rejects_unsafe_scope_before_query() -> None:
    session = MetadataSession()

    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        catalog_search_columns(
            CatalogSearchColumnsInput(
                column_name="EMP%",
                database="EXAMPLE_DB; DROP DATABASE EXAMPLE_DB",
            ),
            session=session,
        )

    assert session.calls == []


def test_metadata_timeout_propagates_with_operation_context() -> None:
    timeout = Timeout("metadata timed out", op="catalog.search_columns")

    with pytest.raises(Timeout) as caught:
        catalog_search_columns(
            CatalogSearchColumnsInput(column_name="EMP%"),
            session=MetadataSession(error=timeout),
        )

    assert caught.value.op == "catalog.search_columns"
