"""Register catalog ops."""
from __future__ import annotations

from snow_kit.registry import OpSpec, register

from .core import (
    catalog_check_write_access,
    catalog_describe_table,
    catalog_get_table_stats,
    catalog_list_tables,
    catalog_preview_table,
    catalog_search_columns,
)
from .models import (
    CatalogCheckWriteAccessInput,
    CatalogCheckWriteAccessOutput,
    CatalogDescribeTableInput,
    CatalogDescribeTableOutput,
    CatalogGetTableStatsInput,
    CatalogGetTableStatsOutput,
    CatalogListTablesInput,
    CatalogListTablesOutput,
    CatalogPreviewTableInput,
    CatalogPreviewTableOutput,
    CatalogSearchColumnsInput,
    CatalogSearchColumnsOutput,
)

register(OpSpec(
    name="catalog.list_tables",
    fn=catalog_list_tables,
    input_model=CatalogListTablesInput,
    output_model=CatalogListTablesOutput,
    posture="read",
    scopes=["snowflake:read"],
    perf={"api": "Snowflake", "method": "SHOW TABLES"},
    examples=[{"input": {"database": "EXAMPLE_DB", "schema": "PUBLIC"}, "cli": "snow-kit catalog list_tables --database EXAMPLE_DB --schema PUBLIC"}],
    keywords=["catalog", "tables"],
))

register(OpSpec(
    name="catalog.describe_table",
    fn=catalog_describe_table,
    input_model=CatalogDescribeTableInput,
    output_model=CatalogDescribeTableOutput,
    posture="read",
    scopes=["snowflake:read"],
    perf={"api": "Snowflake", "method": "DESCRIBE TABLE"},
    examples=[{"input": {"table_name": "EXAMPLE_DB.PUBLIC.MY_TABLE"}, "cli": "snow-kit catalog describe_table --table-name EXAMPLE_DB.PUBLIC.MY_TABLE"}],
    aliases=["describe this table", "inspect table columns"],
    keywords=["catalog", "describe", "table"],
))

register(OpSpec(
    name="catalog.preview_table",
    fn=catalog_preview_table,
    input_model=CatalogPreviewTableInput,
    output_model=CatalogPreviewTableOutput,
    posture="read",
    scopes=["snowflake:read"],
    perf={"api": "Snowflake", "method": "SELECT LIMIT"},
    examples=[{"input": {"table_name": "EXAMPLE_DB.PUBLIC.MY_TABLE", "limit": 10}, "cli": "snow-kit catalog preview_table --table-name EXAMPLE_DB.PUBLIC.MY_TABLE --limit 10"}],
    keywords=["catalog", "preview", "table"],
))

register(OpSpec(
    name="catalog.search_columns",
    fn=catalog_search_columns,
    input_model=CatalogSearchColumnsInput,
    output_model=CatalogSearchColumnsOutput,
    posture="read",
    scopes=["snowflake:read"],
    perf={"api": "Snowflake", "method": "SHOW COLUMNS"},
    examples=[{"input": {"column_name": "USER%"}, "cli": "snow-kit catalog search_columns --column-name USER%"}],
    aliases=["find a column", "search scoped column metadata"],
    keywords=["catalog", "column", "columns", "search"],
))

register(OpSpec(
    name="catalog.get_table_stats",
    fn=catalog_get_table_stats,
    input_model=CatalogGetTableStatsInput,
    output_model=CatalogGetTableStatsOutput,
    posture="read",
    scopes=["snowflake:read"],
    perf={"api": "Snowflake", "method": "SHOW TABLES"},
    examples=[{"input": {"table_name": "EXAMPLE_DB.PUBLIC.MY_TABLE"}, "cli": "snow-kit catalog get_table_stats --table-name EXAMPLE_DB.PUBLIC.MY_TABLE"}],
    keywords=["catalog", "stats", "table"],
))

register(OpSpec(
    name="catalog.check_write_access",
    fn=catalog_check_write_access,
    input_model=CatalogCheckWriteAccessInput,
    output_model=CatalogCheckWriteAccessOutput,
    posture="read",
    scopes=["snowflake:read"],
    perf={"api": "Snowflake", "method": "SHOW GRANTS"},
    examples=[{"input": {"object_name": "EXAMPLE_DB.SCRATCH.MY_TABLE", "operation": "INSERT"}, "cli": "snow-kit catalog check_write_access --object-name EXAMPLE_DB.SCRATCH.MY_TABLE --operation INSERT"}],
    keywords=["grants", "permissions", "write access"],
))
