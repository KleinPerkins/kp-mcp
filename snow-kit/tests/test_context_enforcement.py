"""Warning-first and optional-strict context policy tests."""
from __future__ import annotations

import pytest

from snow_kit.context.enforcement import catalog_scope_warnings, query_context_warnings
from snow_kit.core.config import SnowKitConfig
from snow_kit.core.errors import Permission
from snow_kit.services.catalog.core import catalog_list_tables
from snow_kit.services.catalog.models import CatalogListTablesInput
from snow_kit.services.query.core import query_execute
from snow_kit.services.query.models import QueryExecuteInput


def test_constant_and_metadata_queries_remain_usable() -> None:
    config = SnowKitConfig(context_mode="strict")

    assert query_context_warnings("SELECT 1", [], config=config) == []
    assert query_context_warnings("SHOW TABLES", [], config=config) == []


def test_table_query_warns_by_default(fake_session) -> None:
    fake_session.config = SnowKitConfig(context_mode="warn")

    result = query_execute(
        QueryExecuteInput(query="SELECT COUNT(*) FROM EXAMPLE_DB.PUBLIC.USERS"),
        session=fake_session,
    )

    assert any("context.search" in warning for warning in result.warnings)


def test_table_query_is_rejected_in_strict_mode(fake_session) -> None:
    fake_session.config = SnowKitConfig(context_mode="strict")

    with pytest.raises(Permission, match="Strict context-first mode"):
        query_execute(
            QueryExecuteInput(query="SELECT * FROM EXAMPLE_DB.PUBLIC.USERS"),
            session=fake_session,
        )
    assert fake_session.calls == []


def test_unscoped_catalog_warns_or_rejects(fake_session) -> None:
    fake_session.config = SnowKitConfig(context_mode="warn")

    result = catalog_list_tables(CatalogListTablesInput(), session=fake_session)

    assert any("Unscoped catalog discovery" in warning for warning in result.warnings)
    with pytest.raises(Permission, match="Strict context-first mode"):
        catalog_scope_warnings(
            scoped=False,
            op="catalog.list_tables",
            config=SnowKitConfig(context_mode="strict"),
        )


def test_scoped_catalog_is_allowed_in_strict_mode() -> None:
    assert catalog_scope_warnings(
        scoped=True,
        op="catalog.list_tables",
        config=SnowKitConfig(context_mode="strict"),
    ) == []
