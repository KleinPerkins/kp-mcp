"""Pydantic input / output models for the Drive Activity service."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope


class DriveActivityQueryInput(BaseModel):
    """Input for ``drive_activity.query``: query Drive Activity v2."""

    item_name: str | None = Field(
        default=None,
        description="Item name to filter by, e.g. 'items/FILE_ID'",
    )
    ancestor_name: str | None = Field(
        default=None,
        description="Ancestor folder name to filter by, e.g. 'items/FOLDER_ID'",
    )
    filter: str | None = Field(
        default=None,
        description="Filter string (time + detail.action_detail_case filters)",
    )
    consolidation_strategy: str | None = Field(
        default=None,
        description="Consolidation strategy: 'legacy' or 'none'",
    )
    page_size: int | None = Field(default=None, ge=1, le=1000)
    page_token: str | None = Field(default=None)


class DriveActivityItem(BaseModel):
    """A single Drive activity record (pass-through from API)."""

    raw: dict[str, Any] = Field(description="Raw activity object from the API")


class DriveActivityQueryData(BaseModel):
    """Data payload for ``drive_activity.query``."""

    activities: list[dict[str, Any]]


DriveActivityQueryOutput = OutputEnvelope[DriveActivityQueryData]
