"""Pydantic models for the first-class composition recipes (architecture brief §4).

Every recipe returns a structured envelope whose ``status`` discriminates a
fully-applied run (``"completed"``) from one that failed mid-way and was rolled
back by the LIFO saga (``"rolled_back"``). On rollback the partial identifiers
captured before the failure are still surfaced (e.g. the doc that was created
and then trashed), and ``meta.saga_compensated`` is set on the envelope.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope

_RecipeStatus = Literal["completed", "rolled_back"]


# ─── recipes.build_then_share ─────────────────────────────────────────────────


class BuildThenShareInput(BaseModel):
    """Input for ``recipes.build_then_share``: create a styled Doc, then share it."""

    markdown_content: str = Field(description="Markdown body to convert into a styled Google Doc.")
    title: str = Field(description="Title for the created Google Doc.")
    share_with: str = Field(description="Email address (user or group) to grant access to.")
    role: str = Field(default="reader", description="Permission role: reader | commenter | writer.")
    type: str = Field(default="user", description="Permission type: user | group | domain | anyone.")
    folder_id: str | None = Field(default=None, description="Optional Drive folder to create the Doc in.")
    style_profile: str | None = Field(default=None, description="Optional local Docs style profile name.")
    style_overrides: dict[str, Any] | None = Field(default=None, description="Inline style profile overrides.")


class BuildThenShareData(BaseModel):
    """Data payload for ``recipes.build_then_share``."""

    status: _RecipeStatus
    doc_id: str | None = None
    url: str | None = None
    title: str | None = None
    shared_with: str | None = None
    role: str | None = None


BuildThenShareOutput = OutputEnvelope[BuildThenShareData]


# ─── recipes.template_merge ───────────────────────────────────────────────────


class TemplateMergeInput(BaseModel):
    """Input for ``recipes.template_merge``: copy a template Doc, then merge fields."""

    template_id: str = Field(description="Drive file ID or URL of the template document to copy.")
    replacements: dict[str, str] = Field(
        description="Mapping of literal placeholder text → replacement value (Docs replaceAllText)."
    )
    new_name: str | None = Field(default=None, description="Name for the copied document.")
    folder_id: str | None = Field(default=None, description="Optional Drive folder for the copy.")
    match_case: bool = Field(default=True, description="Case-sensitive placeholder matching.")
    style_profile: str | None = Field(default=None, description="Optional local Docs style profile to apply after merge.")
    style_overrides: dict[str, Any] | None = Field(default=None, description="Inline style profile overrides.")


class TemplateMergeData(BaseModel):
    """Data payload for ``recipes.template_merge``."""

    status: _RecipeStatus
    doc_id: str | None = None
    url: str | None = None
    name: str | None = None
    replacements_applied: int = 0


TemplateMergeOutput = OutputEnvelope[TemplateMergeData]


# ─── recipes.hydrate_then_refine ──────────────────────────────────────────────


class HydrateThenRefineInput(BaseModel):
    """Input for ``recipes.hydrate_then_refine``: read a Doc, then apply refinements."""

    document_id: str = Field(description="Drive/Docs file ID or URL to hydrate then refine.")
    requests: list[dict[str, Any]] = Field(
        description="Docs API batchUpdate request objects to apply as the refinement."
    )
    hydrate_metadata_only: bool = Field(
        default=True,
        description="Hydrate via a metadata-only fetch (no full content export).",
    )
    style_profile: str | None = Field(default=None, description="Optional local Docs style profile to append to the refinement.")
    style_overrides: dict[str, Any] | None = Field(default=None, description="Inline style profile overrides.")


class HydrateThenRefineData(BaseModel):
    """Data payload for ``recipes.hydrate_then_refine``."""

    status: _RecipeStatus
    doc_id: str | None = None
    title: str | None = None
    mime_type: str | None = None
    requests_applied: int = 0
    refine_replies: list[dict[str, Any]] = Field(default_factory=list)


HydrateThenRefineOutput = OutputEnvelope[HydrateThenRefineData]


# ─── recipes.build_styled ─────────────────────────────────────────────────────


class BuildStyledInput(BaseModel):
    """Input for ``recipes.build_styled``: create Markdown Doc, then assert styles."""

    markdown_content: str = Field(description="Markdown body to convert into a styled Google Doc.")
    title: str = Field(description="Title for the created Google Doc.")
    folder_id: str | None = Field(default=None, description="Optional Drive folder to create the Doc in.")
    style_profile: str | None = Field(default=None, description="Local Docs style profile name.")
    style_overrides: dict[str, Any] | None = Field(default=None, description="Inline style profile overrides.")


class BuildStyledData(BaseModel):
    """Data payload for ``recipes.build_styled``."""

    status: _RecipeStatus
    doc_id: str | None = None
    url: str | None = None
    title: str | None = None
    style_requests_applied: int = 0


BuildStyledOutput = OutputEnvelope[BuildStyledData]
