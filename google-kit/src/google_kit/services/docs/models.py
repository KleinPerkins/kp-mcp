"""Pydantic input / output models for all Docs service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from google_kit.core.normalize import OutputEnvelope


# ─── docs.from_markdown ───────────────────────────────────────────────────────


class DocsFromMarkdownInput(BaseModel):
    """Input for ``docs.from_markdown``: convert Markdown to a styled Google Doc.

    ``markdown_content`` is the raw Markdown text.
    ``title`` becomes the Google Doc title.
    ``folder_id`` optionally places the doc in that Drive folder.
    """

    markdown_content: str
    title: str
    folder_id: str | None = None
    style_profile: str | None = None
    style_overrides: dict[str, Any] | None = None


class DocsFromMarkdownData(BaseModel):
    """Data payload for ``docs.from_markdown``."""

    doc_id: str
    url: str
    title: str
    formatting_requests_applied: int


DocsFromMarkdownOutput = OutputEnvelope[DocsFromMarkdownData]


# ─── docs.batch_update ────────────────────────────────────────────────────────


class DocsBatchUpdateInput(BaseModel):
    """Input for ``docs.batch_update``: apply a list of Docs API update requests.

    ``document_id`` — the target Google Doc ID.
    ``requests`` — passthrough list of Docs API request objects (insertText,
        deleteContentRange, updateTextStyle, insertTable, etc.).
    ``write_control`` — optional writeControl dict forwarded verbatim to the API.
    """

    document_id: str
    requests: list[dict[str, Any]]
    write_control: dict[str, Any] | None = None
    style_profile: str | None = None
    style_overrides: dict[str, Any] | None = None


class DocsBatchUpdateData(BaseModel):
    """Data payload for ``docs.batch_update``."""

    document_id: str
    replies: list[Any]
    write_control: dict[str, Any] | None = None


DocsBatchUpdateOutput = OutputEnvelope[DocsBatchUpdateData]


# ─── docs.extract_styles ──────────────────────────────────────────────────────


class DocsExtractStylesInput(BaseModel):
    """Input for ``docs.extract_styles``: read named styles from a Google Doc.

    ``style_profile`` is optional. When set, the extracted profile is also saved
    locally under ``config_dir/doc-styles/<style_profile>.json``.
    """

    document_id: str
    style_profile: str | None = None
    template_doc_id: str | None = None
    tab_id: str | None = None


class DocsExtractStylesData(BaseModel):
    """Data payload for ``docs.extract_styles``."""

    document_id: str
    style_profile: str | None = None
    profile: dict[str, Any]
    saved_path: str | None = None


DocsExtractStylesOutput = OutputEnvelope[DocsExtractStylesData]


# ─── docs.apply_styles ────────────────────────────────────────────────────────


class DocsApplyStylesInput(BaseModel):
    """Input for ``docs.apply_styles``: apply a local style profile to a Doc."""

    document_id: str
    style_profile: str | None = None
    style_overrides: dict[str, Any] | None = None
    mode: str = "definitions"
    dry_run: bool = False
    tab_id: str | None = None


class DocsApplyStylesData(BaseModel):
    """Data payload for ``docs.apply_styles``."""

    document_id: str
    style_profile: str | None = None
    mode: str
    dry_run: bool
    requests: list[dict[str, Any]]
    requests_applied: int
    replies: list[Any] | None = None


DocsApplyStylesOutput = OutputEnvelope[DocsApplyStylesData]


# ─── docs.styles_* local management verbs ─────────────────────────────────────


class DocsStylesViewInput(BaseModel):
    """Input for ``docs.styles_view``: list or inspect local style profiles."""

    style_profile: str | None = None


class DocsStylesViewData(BaseModel):
    """Data payload for ``docs.styles_view``."""

    profiles: list[str]
    default: str | None = None
    selected: str | None = None
    profile: dict[str, Any] | None = None


DocsStylesViewOutput = OutputEnvelope[DocsStylesViewData]


class DocsStylesAddInput(BaseModel):
    """Input for ``docs.styles_add``: create a local style profile."""

    style_profile: str
    document_id: str | None = None
    template_doc_id: str | None = None
    profile_data: dict[str, Any] | None = None
    tab_id: str | None = None


class DocsStylesUpdateInput(BaseModel):
    """Input for ``docs.styles_update``: merge updates into a local profile."""

    style_profile: str
    updates: dict[str, Any]


class DocsStylesRemoveInput(BaseModel):
    """Input for ``docs.styles_remove``: delete a local style profile."""

    style_profile: str


class DocsStylesSetDefaultInput(BaseModel):
    """Input for ``docs.styles_set_default``: copy a profile to ``default``."""

    style_profile: str


class DocsStylesApplyInput(DocsApplyStylesInput):
    """Input for ``docs.styles_apply``: conversational wrapper for apply_styles."""


class DocsStylesDoctorInput(BaseModel):
    """Input for ``docs.styles_doctor``: validate and repair local profiles."""

    seed_default: bool = True


class DocsStylesMutationData(BaseModel):
    """Common local style management result payload."""

    style_profile: str | None = None
    path: str | None = None
    deleted: bool | None = None
    profile: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


DocsStylesAddOutput = OutputEnvelope[DocsStylesMutationData]
DocsStylesUpdateOutput = OutputEnvelope[DocsStylesMutationData]
DocsStylesRemoveOutput = OutputEnvelope[DocsStylesMutationData]
DocsStylesSetDefaultOutput = OutputEnvelope[DocsStylesMutationData]
DocsStylesDoctorOutput = OutputEnvelope[DocsStylesMutationData]
