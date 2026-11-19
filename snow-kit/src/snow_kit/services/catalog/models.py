"""Pydantic models for Snowflake catalog operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from snow_kit.core.normalize import OutputEnvelope


class CatalogListTablesInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    database: str | None = None
    schema_name: str | None = Field(default=None, alias="schema", description="Schema name.")
    pattern: str | None = None
    limit: int = Field(default=100, ge=1, le=10_000)


class CatalogRowsData(BaseModel):
    rows: list[dict[str, Any]]
    count: int
    truncated: bool = False
    execution_time_ms: float


CatalogListTablesOutput = OutputEnvelope[CatalogRowsData]


class CatalogDescribeTableInput(BaseModel):
    table_name: str


CatalogDescribeTableOutput = OutputEnvelope[CatalogRowsData]


class CatalogPreviewTableInput(BaseModel):
    table_name: str
    limit: int = Field(default=10, ge=1, le=100)


CatalogPreviewTableOutput = OutputEnvelope[CatalogRowsData]


class CatalogSearchColumnsInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    column_name: str
    database: str | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    limit: int = Field(default=1_000, ge=1, le=10_000)


CatalogSearchColumnsOutput = OutputEnvelope[CatalogRowsData]


class CatalogGetTableStatsInput(BaseModel):
    table_name: str


class CatalogGetTableStatsData(BaseModel):
    stats: dict[str, Any] | None
    execution_time_ms: float


CatalogGetTableStatsOutput = OutputEnvelope[CatalogGetTableStatsData]


class CatalogCheckWriteAccessInput(BaseModel):
    object_name: str
    operation: str = Field(default="INSERT", description="Write operation to check, e.g. INSERT or CREATE TABLE.")
    role: str | None = Field(default=None, description="Role to use for spec explanation filtering.")
    email: str | None = Field(default=None, description="Optional email for spec role exploration.")


class CatalogCheckWriteAccessData(BaseModel):
    object_name: str
    operation: str
    required_privilege: str
    active_role: str | None
    has_snowflake_grant: bool
    matching_grants: list[dict[str, str]]
    live_grants_decisive: bool
    spec_available: bool
    spec_revision: str | None
    spec_matches: list[dict[str, Any]]
    roles_for_email: list[str]


CatalogCheckWriteAccessOutput = OutputEnvelope[CatalogCheckWriteAccessData]
