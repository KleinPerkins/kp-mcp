"""Register query ops."""
from __future__ import annotations

from snow_kit.core.flags import WRITE_FLAG
from snow_kit.registry import OpSpec, register

from .core import query_analyze, query_execute, query_execute_write
from .models import (
    QueryAnalyzeInput,
    QueryAnalyzeOutput,
    QueryExecuteInput,
    QueryExecuteOutput,
    QueryExecuteWriteInput,
    QueryExecuteWriteOutput,
)

register(OpSpec(
    name="query.execute",
    fn=query_execute,
    input_model=QueryExecuteInput,
    output_model=QueryExecuteOutput,
    posture="read",
    scopes=["snowflake:read"],
    perf={"api": "Snowflake", "timeout_seconds": 25, "max_rows": 10_000},
    formatting={"default": "normalized-json"},
    examples=[{"input": {"query": "SELECT 1"}, "cli": "snow-kit query execute --query 'SELECT 1'"}],
    aliases=["execute snowflake query", "run this read-only query"],
    keywords=["read-only", "snowflake", "sql", "query"],
))

register(OpSpec(
    name="query.analyze",
    fn=query_analyze,
    input_model=QueryAnalyzeInput,
    output_model=QueryAnalyzeOutput,
    posture="read",
    scopes=["snowflake:read"],
    perf={"api": "Snowflake", "method": "EXPLAIN"},
    formatting={"default": "normalized-json"},
    examples=[{"input": {"query": "SELECT * FROM MY_TABLE"}, "cli": "snow-kit query analyze --query 'SELECT * FROM MY_TABLE'"}],
    aliases=["analyze this sql", "explain sql"],
    keywords=["explain", "performance", "sql"],
))

register(OpSpec(
    name="query.execute_write",
    fn=query_execute_write,
    input_model=QueryExecuteWriteInput,
    output_model=QueryExecuteWriteOutput,
    posture="write",
    scopes=["snowflake:write"],
    perf={"api": "Snowflake", "requires": "SNOW_KIT_ENABLE_WRITE=1"},
    formatting={"default": "normalized-json"},
    examples=[{
        "input": {"query": "INSERT INTO SCRATCH.DEMO VALUES (1)", "confirm_write": True, "justification": "scratch smoke"},
        "cli": "SNOW_KIT_ENABLE_WRITE=1 snow-kit query execute_write --query 'INSERT ...' --confirm-write --justification 'scratch smoke'",
    }],
    aliases=["execute snowflake write"],
    keywords=["snowflake", "write", "sql"],
    flag=WRITE_FLAG,
))
