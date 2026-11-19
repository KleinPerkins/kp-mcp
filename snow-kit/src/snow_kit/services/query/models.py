"""Pydantic models for Snowflake query operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from snow_kit.core.normalize import OutputEnvelope


class ContextReference(BaseModel):
    """Opaque approved-context reference returned by context.search."""

    document_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    revision: str = Field(pattern=r"^[a-f0-9]{40,64}$")


class QueryExecuteInput(BaseModel):
    query: str = Field(description="Read-only SQL query: SELECT, SHOW, DESCRIBE, EXPLAIN, USE, or WITH.")
    max_rows: int | None = Field(default=None, ge=1, le=10_000, description="Optional row cap.")
    context_refs: list[ContextReference] = Field(
        default_factory=list,
        max_length=10,
        description="Validated document_id/revision pairs returned by context.search.",
    )


class QueryExecuteData(BaseModel):
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    statement_type: str
    execution_time_ms: float


QueryExecuteOutput = OutputEnvelope[QueryExecuteData]


class QueryAnalyzeInput(BaseModel):
    query: str = Field(description="Read-only SQL query to EXPLAIN and analyze.")
    context_refs: list[ContextReference] = Field(
        default_factory=list,
        max_length=10,
        description="Validated document_id/revision pairs returned by context.search.",
    )


class QueryAnalyzeData(BaseModel):
    execution_plan: list[dict[str, Any]]
    performance_issues: list[str]
    recommendations: list[str]
    execution_time_ms: float


QueryAnalyzeOutput = OutputEnvelope[QueryAnalyzeData]


class QueryExecuteWriteInput(BaseModel):
    query: str = Field(description="Single write SQL statement gated by SNOW_KIT_ENABLE_WRITE=1.")
    confirm_write: bool = Field(default=False, description="Must be true for write execution.")
    justification: str = Field(default="", description="Human-readable reason for audit context.")


class QueryExecuteWriteData(BaseModel):
    operation: str
    targets: list[str]
    affected_rows: int
    execution_time_ms: float


QueryExecuteWriteOutput = OutputEnvelope[QueryExecuteWriteData]
