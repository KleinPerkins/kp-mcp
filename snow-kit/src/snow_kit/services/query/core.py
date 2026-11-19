"""Core functions for Snowflake query operations."""
from __future__ import annotations

from typing import Any

from snow_kit.context.enforcement import query_context_warnings
from snow_kit.core.config import SnowKitConfig
from snow_kit.core.connection import SnowflakeSession, default_session
from snow_kit.core.grants import has_grant, normalize_grants
from snow_kit.core.normalize import Meta
from snow_kit.core.sql import ensure_read_only
from snow_kit.core.sql_policy import classify_write

from .models import (
    QueryAnalyzeData,
    QueryAnalyzeInput,
    QueryAnalyzeOutput,
    QueryExecuteData,
    QueryExecuteInput,
    QueryExecuteOutput,
    QueryExecuteWriteData,
    QueryExecuteWriteInput,
    QueryExecuteWriteOutput,
)


def query_execute(inp: QueryExecuteInput, *, session: SnowflakeSession | Any = None) -> QueryExecuteOutput:
    """Execute a read-only Snowflake query and return normalized JSON rows."""
    session = session or default_session()
    stype = ensure_read_only(inp.query)
    config = getattr(session, "config", None) or SnowKitConfig.from_env()
    warnings = query_context_warnings(inp.query, inp.context_refs, config=config)
    result = session.execute(inp.query, op="query.execute", max_rows=inp.max_rows)
    if result.truncated:
        warnings.append("Results truncated to the configured row cap; add LIMIT for smaller result sets.")
    return QueryExecuteOutput(
        data=QueryExecuteData(
            rows=result.rows,
            row_count=result.row_count,
            truncated=result.truncated,
            statement_type=stype,
            execution_time_ms=result.execution_time_ms,
        ),
        warnings=warnings,
        meta=Meta(op="query.execute", latency_ms=result.execution_time_ms),
    )


def query_analyze(inp: QueryAnalyzeInput, *, session: SnowflakeSession | Any = None) -> QueryAnalyzeOutput:
    """Analyze a read-only query with EXPLAIN plus simple performance heuristics."""
    session = session or default_session()
    ensure_read_only(inp.query)
    from sqlglot import exp, parse_one

    root = parse_one(inp.query, read="snowflake")
    if isinstance(root, exp.Command):
        # The read-only gate has already validated this EXPLAIN and its body.
        explain_query = inp.query
    elif isinstance(root, (exp.Select, exp.SetOperation, exp.Subquery)):
        explain_query = f"EXPLAIN {inp.query}"
    else:
        raise ValueError("query.analyze requires a read query or an existing EXPLAIN query.")
    config = getattr(session, "config", None) or SnowKitConfig.from_env()
    context_warnings = query_context_warnings(inp.query, inp.context_refs, config=config)
    result = session.execute(explain_query, op="query.analyze")
    upper = inp.query.upper()
    issues: list[str] = []
    recommendations: list[str] = []
    if "SELECT *" in upper or "SELECT\n*" in upper:
        issues.append("Using SELECT * retrieves every column.")
        recommendations.append("Select only needed columns.")
    if "SELECT" in upper and "LIMIT" not in upper and "COUNT" not in upper:
        issues.append("No LIMIT clause may return a large result set.")
        recommendations.append("Add LIMIT when sampling.")
    if "SELECT" in upper and "WHERE" not in upper and "LIMIT" not in upper:
        issues.append("No WHERE clause may scan a large table.")
        recommendations.append("Filter on partition or selective columns.")
    if "DISTINCT" in upper:
        issues.append("DISTINCT can require expensive sorting/deduplication.")
        recommendations.append("Use GROUP BY or join keys when possible.")
    if not issues:
        issues.append("No obvious issues detected.")
    if not recommendations:
        recommendations.append("Query looks reasonable.")
    return QueryAnalyzeOutput(
        data=QueryAnalyzeData(
            execution_plan=result.rows,
            performance_issues=issues,
            recommendations=recommendations,
            execution_time_ms=result.execution_time_ms,
        ),
        warnings=context_warnings,
        meta=Meta(op="query.analyze", latency_ms=result.execution_time_ms),
    )


def query_execute_write(inp: QueryExecuteWriteInput, *, session: SnowflakeSession | Any = None) -> QueryExecuteWriteOutput:
    """Execute one gated Snowflake write after confirmation, AST policy, and grant preflight."""
    if not inp.confirm_write or not inp.justification.strip():
        raise PermissionError("query.execute_write requires confirm_write=true and a non-empty justification.")
    session = session or default_session()
    config: SnowKitConfig = getattr(session, "config", SnowKitConfig.from_env())
    context = session.current_context()
    plan = classify_write(
        inp.query,
        current_database=str(context.get("DATABASE") or config.database),
        current_schema=str(context.get("SCHEMA") or config.schema or ""),
        schema_patterns=config.write_schema_patterns,
    )
    grants = normalize_grants(session.show_current_role_grants())
    denied = [target for target in plan.targets if not has_grant(grants, object_name=target, operation=plan.operation)[0]]
    if denied:
        raise PermissionError(
            "Snowflake current-role grant preflight denied write for "
            + ", ".join(denied)
            + "; use catalog.check_write_access for remediation context."
        )
    result = session.execute(inp.query, op="query.execute_write", max_rows=1)
    return QueryExecuteWriteOutput(
        data=QueryExecuteWriteData(
            operation=plan.operation,
            targets=list(plan.targets),
            affected_rows=result.row_count,
            execution_time_ms=result.execution_time_ms,
        ),
        meta=Meta(op="query.execute_write", latency_ms=result.execution_time_ms),
    )
