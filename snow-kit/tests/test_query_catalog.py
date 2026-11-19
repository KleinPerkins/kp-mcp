"""Offline read parity tests for query and catalog operations."""
from __future__ import annotations

import pytest

from snow_kit.services.catalog.core import (
    catalog_describe_table,
    catalog_get_table_stats,
    catalog_list_tables,
    catalog_preview_table,
    catalog_search_columns,
)
from snow_kit.services.catalog.models import (
    CatalogDescribeTableInput,
    CatalogGetTableStatsInput,
    CatalogListTablesInput,
    CatalogPreviewTableInput,
    CatalogSearchColumnsInput,
)
from snow_kit.services.query.core import query_analyze, query_execute
from snow_kit.services.query.models import QueryAnalyzeInput, QueryExecuteInput


def test_query_execute_read_only(fake_session) -> None:
    out = query_execute(QueryExecuteInput(query="SELECT 1"), session=fake_session)

    assert out.data.rows == [{"ONE": 1}]
    assert out.data.statement_type == "SELECT"
    assert out.meta.op == "query.execute"


def test_query_execute_blocks_writes(fake_session) -> None:
    with pytest.raises(PermissionError):
        query_execute(QueryExecuteInput(query="DELETE FROM EXAMPLE_DB.SCRATCH.DEMO"), session=fake_session)


@pytest.mark.parametrize(
    "query",
    [
        "USE ROLE ACCOUNTADMIN",
        "USE\nROLE ACCOUNTADMIN",
        "USE\tSECONDARY ROLES ALL",
        "USE /* role switch */ ROLE ACCOUNTADMIN",
    ],
)
def test_query_execute_blocks_use_role(query: str, fake_session) -> None:
    with pytest.raises(PermissionError):
        query_execute(QueryExecuteInput(query=query), session=fake_session)


def test_query_analyze_returns_heuristics(fake_session) -> None:
    out = query_analyze(QueryAnalyzeInput(query="SELECT * FROM EXAMPLE_DB.PUBLIC.USERS"), session=fake_session)

    assert out.data.execution_plan == [{"PLAN": "table scan"}]
    assert any("SELECT *" in issue for issue in out.data.performance_issues)


def test_catalog_read_ops(fake_session) -> None:
    assert catalog_list_tables(CatalogListTablesInput(database="EXAMPLE_DB", schema="PUBLIC"), session=fake_session).data.count == 1
    assert catalog_describe_table(CatalogDescribeTableInput(table_name="EXAMPLE_DB.PUBLIC.USERS"), session=fake_session).data.rows[0]["name"] == "ID"
    assert catalog_preview_table(CatalogPreviewTableInput(table_name="EXAMPLE_DB.PUBLIC.USERS"), session=fake_session).data.rows == [{"ONE": 1}]
    assert catalog_search_columns(CatalogSearchColumnsInput(column_name="USER%"), session=fake_session).data.rows[0]["COLUMN_NAME"] == "USER_ID"
    stats = catalog_get_table_stats(CatalogGetTableStatsInput(table_name="EXAMPLE_DB.PUBLIC.USERS"), session=fake_session)
    assert stats.data.stats and stats.data.stats["SIZE_READABLE"] == "2.00 MB"
