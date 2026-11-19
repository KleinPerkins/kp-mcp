"""Shared offline Snowflake fixtures for snow-kit tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from snow_kit.core.config import SnowKitConfig
from snow_kit.core.connection import QueryResult


class FakeSession:
    def __init__(self, *, spec_path: Path | None = None) -> None:
        self.config = SnowKitConfig(spec_path=spec_path)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | None = None, *, op: str, max_rows: int | None = None) -> QueryResult:
        del max_rows
        self.calls.append((sql, tuple(params or ())))
        upper = sql.upper()
        if "EXPLAIN" in upper:
            return QueryResult([{"PLAN": "table scan"}], ["PLAN"], 1, False, 2.0)
        if "SHOW TABLES" in upper:
            if "STARTS WITH" in upper:
                return QueryResult(
                    [
                        {
                            "created_on": "2026-01-01 00:00:00+00:00",
                            "name": "USERS",
                            "database_name": "EXAMPLE_DB",
                            "schema_name": "PUBLIC",
                            "kind": "TABLE",
                            "rows": 10,
                            "bytes": 2_000_000,
                            "cluster_by": "",
                            "is_dynamic": "N",
                            "is_event": "N",
                            "is_external": "N",
                            "is_hybrid": "N",
                            "is_iceberg": "N",
                            "is_immutable": "N",
                        }
                    ],
                    [
                        "created_on",
                        "name",
                        "database_name",
                        "schema_name",
                        "kind",
                        "rows",
                        "bytes",
                        "cluster_by",
                        "is_dynamic",
                        "is_event",
                        "is_external",
                        "is_hybrid",
                        "is_iceberg",
                        "is_immutable",
                    ],
                    1,
                    False,
                    6.0,
                )
            return QueryResult([{"name": "USERS", "rows": 10}], ["name", "rows"], 1, False, 3.0)
        if "SHOW COLUMNS" in upper:
            return QueryResult(
                [
                    {
                        "table_name": "USERS",
                        "schema_name": "PUBLIC",
                        "column_name": "USER_ID",
                        "data_type": '{"type":"FIXED","precision":38,"scale":0,"nullable":false}',
                        "null?": False,
                        "kind": "COLUMN",
                        "database_name": "EXAMPLE_DB",
                    }
                ],
                ["table_name", "schema_name", "column_name", "data_type", "null?", "kind", "database_name"],
                1,
                False,
                5.0,
            )
        if "DESCRIBE TABLE" in upper:
            return QueryResult([{"name": "ID", "type": "NUMBER"}], ["name", "type"], 1, False, 4.0)
        if "CURRENT_USER" in upper:
            return QueryResult([{"USER": "EXAMPLE_USER", "ROLE": "U_EXAMPLE", "DATABASE": "EXAMPLE_DB", "SCHEMA": "SCRATCH"}], ["USER", "ROLE", "DATABASE", "SCHEMA"], 1, False, 1.0)
        if "INSERT INTO" in upper:
            return QueryResult([], [], 1, False, 7.0)
        return QueryResult([{"ONE": 1}], ["ONE"], 1, False, 1.5)

    def current_context(self) -> dict[str, Any]:
        return {"USER": "EXAMPLE_USER", "ROLE": "U_EXAMPLE", "DATABASE": "EXAMPLE_DB", "SCHEMA": "SCRATCH"}

    def show_current_role_grants(self) -> list[dict[str, Any]]:
        return [
            {"privilege": "INSERT", "granted_on": "TABLE", "name": "EXAMPLE_DB.SCRATCH.DEMO", "grantee_name": "U_EXAMPLE"},
            {"privilege": "CREATE TABLE", "granted_on": "SCHEMA", "name": "EXAMPLE_DB.SCRATCH", "grantee_name": "U_EXAMPLE"},
        ]


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()
