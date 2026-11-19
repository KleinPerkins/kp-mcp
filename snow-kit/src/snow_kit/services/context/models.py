"""Pydantic contracts for bounded authoritative-context operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from snow_kit.core.normalize import OutputEnvelope


class ContextProvenance(BaseModel):
    source_id: str
    revision: str
    relative_path: str


class ContextSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class ContextSearchResult(BaseModel):
    document_id: str
    title: str
    snippet: str
    score: int
    authority: str
    metadata_complete: bool
    provenance: ContextProvenance
    warnings: list[str] = Field(default_factory=list)


class ContextSearchData(BaseModel):
    query: str
    revision: str
    results: list[ContextSearchResult]
    count: int
    truncated: bool
    next_action: str | None = None


ContextSearchOutput = OutputEnvelope[ContextSearchData]


class ContextGetInput(BaseModel):
    document_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    revision: str = Field(pattern=r"^[a-f0-9]{40,64}$")
    section: str | None = Field(default=None, max_length=200)
    max_chars: int = Field(default=6_000, ge=200, le=12_000)


class ContextGetData(BaseModel):
    document_id: str
    title: str
    section: str | None
    content: str
    truncated: bool
    authority: str
    metadata_complete: bool
    provenance: ContextProvenance


ContextGetOutput = OutputEnvelope[ContextGetData]
