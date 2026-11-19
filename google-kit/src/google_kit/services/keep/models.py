"""Pydantic input / output models for all Keep service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope


class KeepListInput(BaseModel):
    """Input for ``keep.list``: list notes."""

    page_size: int = Field(default=50, ge=1, le=1000)
    filter: str | None = None


class NoteItem(BaseModel):
    """One Keep note entry (normalized)."""

    name: str
    title: str
    body_text: str | None = None
    create_time: str | None = None
    update_time: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class KeepListData(BaseModel):
    """Data payload for ``keep.list``."""

    count: int
    notes: list[NoteItem]


KeepListOutput = OutputEnvelope[KeepListData]


class KeepGetInput(BaseModel):
    """Input for ``keep.get``: get a single note by resource name."""

    note_id: str = Field(..., description="Note resource name, e.g. 'notes/abc123'")


class KeepGetData(BaseModel):
    """Data payload for ``keep.get``."""

    name: str
    title: str
    body_text: str | None = None
    create_time: str | None = None
    update_time: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


KeepGetOutput = OutputEnvelope[KeepGetData]


class KeepCreateInput(BaseModel):
    """Input for ``keep.create``: create a new note."""

    title: str
    body_text: str | None = None
    list_items: str | None = Field(
        default=None,
        description="Comma-separated checklist items. If set, creates a list note instead of a text note.",
    )


class KeepCreateData(BaseModel):
    """Data payload for ``keep.create``."""

    name: str
    title: str


KeepCreateOutput = OutputEnvelope[KeepCreateData]


class KeepDeleteInput(BaseModel):
    """Input for ``keep.delete``: trash a note by resource name."""

    note_id: str = Field(..., description="Note resource name, e.g. 'notes/abc123'")


class KeepDeleteData(BaseModel):
    """Data payload for ``keep.delete``."""

    deleted: bool
    note_id: str


KeepDeleteOutput = OutputEnvelope[KeepDeleteData]
