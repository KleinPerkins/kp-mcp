"""Adversarial offline checks at the real read service/connector boundary."""
from __future__ import annotations

import pytest

from snow_kit.core.sql import ensure_read_only
from snow_kit.services.query.core import query_analyze, query_execute
from snow_kit.services.query.models import QueryAnalyzeInput, QueryExecuteInput


@pytest.mark.parametrize("query", [
    "WITH x AS (SELECT 1) DELETE\nFROM t",
    "WITH x AS (SELECT 1) DELETE/*gap*/FROM t",
    "WITH x AS (SELECT 1) UPDATE\nt SET a=1",
    "WITH x AS (SELECT 1) INSERT\nINTO t SELECT * FROM x",
    "WITH x AS (DELETE\nFROM t) SELECT * FROM x",
    "WITH x AS (UPDATE/*gap*/t SET a=1) SELECT * FROM x",
    "WITH p AS PROCEDURE () RETURNS STRING LANGUAGE SQL AS $$ BEGIN DELETE FROM t; RETURN 1; END; $$ CALL p()",
    "WITH x AS (SELECT 1) CALL\np()",
    "WITH x AS (SELECT 1) CALL/*gap*/p()",
    "SELECT 1; DELETE\nFROM t",
    "SELECT 1; CALL/*gap*/p()",
    "SELECT 1; USE ROLE ACCOUNTADMIN",
    "SELECT * INTO t2 FROM t",
    "SELECT * FROM t FOR UPDATE",
    "SELECT seq.NEXTVAL",
    "SELECT SYSTEM$CANCEL_QUERY('synthetic-query-id')",
    "EXECUTE/*gap*/IMMEDIATE 'DELETE FROM t'",
    "COPY INTO @stage FROM (SELECT 1)",
    "CALL\np()",
    "BEGIN DELETE FROM t; END",
    "USE/*gap*/ROLE ACCOUNTADMIN",
    "USE SECONDARY/*gap*/ROLES ALL",
    "EXPLAIN DELETE\nFROM t",
    "EXPLAIN SELECT 1; CALL p()",
    "", "-- only a comment", "SELECT (",
])
@pytest.mark.parametrize("analyze", [False, True])
def test_effectful_or_unparsed_sql_never_reaches_connector(query, analyze, fake_session):
    with pytest.raises(PermissionError):
        if analyze:
            query_analyze(QueryAnalyzeInput(query=query), session=fake_session)
        else:
            query_execute(QueryExecuteInput(query=query), session=fake_session)
    assert fake_session.calls == []


@pytest.mark.parametrize("query,kind", [
    ("SELECT 1", "SELECT"),
    ("-- a comment\nSELECT 'DELETE FROM t; CALL p()' AS text", "SELECT"),
    ("SELECT '/* literal */ -- text' AS text", "SELECT"),
    ("WITH x AS (SELECT 1 AS n) SELECT * FROM x", "WITH"),
    ("WITH x AS (SELECT 1) SELECT * FROM x UNION ALL SELECT 2", "WITH"),
    ("SELECT 1 UNION SELECT 2", "SELECT"),
    ("SHOW TABLES", "SHOW"),
    ("DESC TABLE EXAMPLE_DB.PUBLIC.DEMO", "DESC"),
    ("DESCRIBE TABLE EXAMPLE_DB.PUBLIC.DEMO", "DESCRIBE"),
    ("USE DATABASE EXAMPLE_DB", "USE"),
    ("USE SCHEMA PUBLIC", "USE"),
    ("USE WAREHOUSE EXAMPLE_WH", "USE"),
    ("EXPLAIN SELECT 1", "EXPLAIN"),
    ("EXPLAIN USING JSON WITH x AS (SELECT 1) SELECT * FROM x", "EXPLAIN"),
])
def test_supported_reads_are_admitted(query, kind, fake_session):
    assert ensure_read_only(query) == kind
    out = query_execute(QueryExecuteInput(query=query), session=fake_session)
    assert out.data.statement_type == kind
    assert fake_session.calls == [(query, ())]


@pytest.mark.parametrize("query", [
    "SHOW TABLES", "DESC TABLE EXAMPLE_DB.PUBLIC.DEMO",
    "DESCRIBE TABLE EXAMPLE_DB.PUBLIC.DEMO", "USE DATABASE EXAMPLE_DB",
    "USE SCHEMA PUBLIC", "USE WAREHOUSE EXAMPLE_WH",
])
def test_analyze_rejects_metadata_and_context_before_connector(query, fake_session):
    with pytest.raises(ValueError, match="query.analyze requires"):
        query_analyze(QueryAnalyzeInput(query=query), session=fake_session)
    assert fake_session.calls == []


@pytest.mark.parametrize("query,explained", [
    ("SELECT 1", "EXPLAIN SELECT 1"),
    ("WITH x AS (SELECT 1) SELECT * FROM x", "EXPLAIN WITH x AS (SELECT 1) SELECT * FROM x"),
    ("SELECT 1 UNION SELECT 2", "EXPLAIN SELECT 1 UNION SELECT 2"),
    ("(SELECT 1)", "EXPLAIN (SELECT 1)"),
    ("EXPLAIN SELECT 1", "EXPLAIN SELECT 1"),
    ("EXPLAIN/*gap*/SELECT 1", "EXPLAIN/*gap*/SELECT 1"),
    ("EXPLAIN USING JSON SELECT 1", "EXPLAIN USING JSON SELECT 1"),
])
def test_analyze_explains_queries_exactly_once(query, explained, fake_session):
    query_analyze(QueryAnalyzeInput(query=query), session=fake_session)
    assert fake_session.calls == [(explained, ())]
