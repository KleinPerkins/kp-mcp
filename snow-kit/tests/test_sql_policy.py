"""AST policy tests for the hidden write path."""
from __future__ import annotations

import pytest

from snow_kit.core.sql_policy import SqlPolicyError, classify_write


def test_classify_insert() -> None:
    plan = classify_write(
        "INSERT INTO DEMO VALUES (1)",
        current_database="EXAMPLE_DB",
        current_schema="SCRATCH",
    )

    assert plan.operation == "INSERT"
    assert plan.targets == ("EXAMPLE_DB.SCRATCH.DEMO",)


def test_rejects_admin_statement() -> None:
    with pytest.raises(SqlPolicyError):
        classify_write("GRANT SELECT ON TABLE A TO ROLE B", current_database="EXAMPLE_DB", current_schema="SCRATCH")


def test_rejects_create_or_replace() -> None:
    with pytest.raises(SqlPolicyError):
        classify_write("CREATE OR REPLACE TABLE DEMO (ID NUMBER)", current_database="EXAMPLE_DB", current_schema="SCRATCH")


def test_drop_table_requires_scratch_schema() -> None:
    with pytest.raises(SqlPolicyError):
        classify_write("DROP TABLE EXAMPLE_DB.PUBLIC.DEMO", current_database="EXAMPLE_DB", current_schema="PUBLIC")

    plan = classify_write("DROP TABLE EXAMPLE_DB.SCRATCH.DEMO", current_database="EXAMPLE_DB", current_schema="SCRATCH")
    assert plan.operation == "DROP TABLE"


def test_drop_table_rejects_substring_false_positives() -> None:
    with pytest.raises(SqlPolicyError):
        classify_write("DROP TABLE EXAMPLE_DB.ATTEMPT.DEMO", current_database="EXAMPLE_DB", current_schema="ATTEMPT")
    with pytest.raises(SqlPolicyError):
        classify_write("DROP TABLE EXAMPLE_DB.TEMPLATE.DEMO", current_database="EXAMPLE_DB", current_schema="TEMPLATE")


def test_create_table_if_not_exists_target() -> None:
    plan = classify_write(
        "CREATE TABLE IF NOT EXISTS EXAMPLE_DB.SCRATCH.DEMO (ID NUMBER)",
        current_database="EXAMPLE_DB",
        current_schema="SCRATCH",
    )

    assert plan.operation == "CREATE TABLE"
    assert plan.targets == ("EXAMPLE_DB.SCRATCH.DEMO",)
