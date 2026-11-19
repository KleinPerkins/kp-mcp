"""Pydantic input / output models for all Drive service operations."""
from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from google_kit.core.normalize import OutputEnvelope

_DriveDocType = Literal["doc", "sheet", "slide", "folder"]
_SearchDocType = Literal["doc", "sheet", "slide", "site", "all-google"]
_ScopeType = Literal["user", "allDrives", "domain"]

# ─── drive.fetch ──────────────────────────────────────────────────────────────


class DriveFetchInput(BaseModel):
    """Input for ``drive.fetch``: fetch a Drive item's content."""

    url_or_id: str = Field(description="Drive file URL or file ID; Google Sites URLs are routed to the Sites path.")
    metadata_only: bool = False


class DriveFetchData(BaseModel):
    """Data payload for ``drive.fetch``."""

    id: str
    title: str
    mime_type: str
    platform: str
    content: str | None = None
    fetch_method: str
    web_url: str | None = None


DriveFetchOutput = OutputEnvelope[DriveFetchData]


# ─── drive.create ─────────────────────────────────────────────────────────────


class DriveCreateInput(BaseModel):
    """Input for ``drive.create``: create a new Drive file or folder."""

    title: str
    doc_type: _DriveDocType = "doc"
    folder_id: str | None = None


class DriveCreateData(BaseModel):
    """Data payload for ``drive.create``."""

    id: str
    url: str
    title: str
    doc_type: str


DriveCreateOutput = OutputEnvelope[DriveCreateData]


# ─── drive.search ─────────────────────────────────────────────────────────────


class DriveFileItem(BaseModel):
    """One file result from ``drive.search``."""

    id: str
    title: str
    type: str
    modified: str | None = None
    owners: list[str]
    url: str
    shared: bool = False


class DriveSearchInput(BaseModel):
    """Input for ``drive.search``: search Drive with rich filtering."""

    query: str | None = Field(default=None, description="Full-text search string; maps to Drive 'fullText contains' clause.")
    name: str | None = Field(default=None, description="Title/name search; maps to Drive 'name contains' clause.")
    doc_type: _SearchDocType | None = None
    owner: str | None = None
    after: str | None = None
    before: str | None = None
    created_after: str | None = None
    created_before: str | None = None
    shared_with_me: bool = False
    starred: bool = False
    scope: _ScopeType = "allDrives"
    sort: str = "modifiedTime desc"
    limit: int = Field(default=25, ge=1, le=1000)


class DriveSearchData(BaseModel):
    """Data payload for ``drive.search``."""

    query: str
    count: int
    results: list[DriveFileItem]
    truncated: bool = False


DriveSearchOutput = OutputEnvelope[DriveSearchData]


# ─── drive.upload ─────────────────────────────────────────────────────────────


class DriveUploadInput(BaseModel):
    """Input for ``drive.upload``: upload a local file to Google Drive.

    Provide EXACTLY ONE source of content:
      - ``path``: an absolute/relative path to a local file. The file is
        streamed from disk (resumable ``MediaFileUpload``) — any size, any
        binary content. ``filename`` defaults to the path's basename.
      - ``content_b64``: base64-encoded inline bytes (small files only; a single
        tool call cannot carry large base64 payloads — prefer ``path``). The
        decoded payload is capped at 10 MiB (``MAX_INLINE_UPLOAD_BYTES``); larger
        content must use ``path``.

    MIME type resolution: explicit ``mime_type`` wins; otherwise it is guessed
    from ``path``/``filename`` extension; otherwise ``application/octet-stream``.

    Sharing is PRIVATE by default (``share="private"`` makes no permission call —
    the file stays owner-private). Pass ``share="anyone_reader"`` to explicitly
    grant a world-readable (``type=anyone, role=reader``) permission; this is
    refused unless ``GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE=1``. A ``path`` source
    must also resolve within ``GOOGLE_KIT_UPLOAD_ROOT`` (default: home).

    When ``folder_id`` is absent, the file is placed in a folder named
    ``folder_name`` (created if it does not exist; default: google-kit-uploads).
    """

    path: str | None = Field(default=None, description="Local file path to stream from disk (resumable). Mutually exclusive with content_b64.")
    content_b64: str | None = Field(default=None, description="Base64-encoded inline content. Mutually exclusive with path.")
    filename: str | None = Field(default=None, description="Display/MIME basename; defaults to os.path.basename(path) when path is given.")
    title: str | None = None
    mime_type: str | None = None
    folder_id: str | None = None
    folder_name: str = "google-kit-uploads"
    share: Literal["private", "anyone_reader"] = "private"

    @model_validator(mode="after")
    def _validate_source(self) -> "DriveUploadInput":
        if (self.content_b64 is None) == (self.path is None):
            raise ValueError(
                "drive.upload requires exactly one of 'path' or 'content_b64' "
                "(both given or neither given is invalid)."
            )
        if self.path is not None and not self.filename:
            self.filename = os.path.basename(self.path)
        return self


class DriveUploadData(BaseModel):
    """Data payload for ``drive.upload``."""

    id: str
    url: str
    name: str
    mime_type: str
    shared: bool = False


DriveUploadOutput = OutputEnvelope[DriveUploadData]


# ─── drive.copy ───────────────────────────────────────────────────────────────


class DriveCopyInput(BaseModel):
    """Input for ``drive.copy``: copy a Drive file."""

    file_id: str
    name: str | None = None
    folder_id: str | None = None


class DriveCopyData(BaseModel):
    """Data payload for ``drive.copy``."""

    id: str
    url: str
    name: str


DriveCopyOutput = OutputEnvelope[DriveCopyData]


# ─── drive.update ─────────────────────────────────────────────────────────────


class DriveUpdateInput(BaseModel):
    """Input for ``drive.update``: rename, move, or modify metadata on a Drive file."""

    file_id: str
    name: str | None = None
    description: str | None = None
    starred: bool | None = None
    add_parents: list[str] | None = None
    remove_parents: list[str] | None = None


class DriveUpdateData(BaseModel):
    """Data payload for ``drive.update``."""

    id: str
    name: str
    parents: list[str]


DriveUpdateOutput = OutputEnvelope[DriveUpdateData]


# ─── drive.trash ──────────────────────────────────────────────────────────────


class DriveTrashInput(BaseModel):
    """Input for ``drive.trash``: trash or untrash a Drive file via files.update."""

    file_id: str
    untrash: bool = False


class DriveTrashData(BaseModel):
    """Data payload for ``drive.trash``."""

    id: str
    trashed: bool


DriveTrashOutput = OutputEnvelope[DriveTrashData]


# ─── drive.permissions ────────────────────────────────────────────────────────


class DrivePermissionsInput(BaseModel):
    """Input for ``drive.permissions``: list, create, or delete sharing permissions."""

    file_id: str
    action: Literal["list", "create", "delete"]
    role: str | None = None
    type: str | None = None
    email_address: str | None = None
    domain: str | None = None
    permission_id: str | None = None


class DrivePermissionsData(BaseModel):
    """Data payload for ``drive.permissions``."""

    action: str
    permissions: list[dict[str, Any]] | None = None
    permission: dict[str, Any] | None = None
    deleted: bool | None = None


DrivePermissionsOutput = OutputEnvelope[DrivePermissionsData]


# ─── drive.comments ───────────────────────────────────────────────────────────


class DriveCommentsInput(BaseModel):
    """Input for ``drive.comments``: list or create comments on a Drive file."""

    file_id: str
    action: Literal["list", "create"]
    content: str | None = None


class DriveCommentsData(BaseModel):
    """Data payload for ``drive.comments``."""

    action: str
    comments: list[dict[str, Any]] | None = None
    comment: dict[str, Any] | None = None


DriveCommentsOutput = OutputEnvelope[DriveCommentsData]


# ─── drive.revisions ──────────────────────────────────────────────────────────


class DriveRevisionsInput(BaseModel):
    """Input for ``drive.revisions``: list or get revisions of a Drive file."""

    file_id: str
    revision_id: str | None = None


class DriveRevisionsData(BaseModel):
    """Data payload for ``drive.revisions``."""

    revisions: list[dict[str, Any]] | None = None
    revision: dict[str, Any] | None = None


DriveRevisionsOutput = OutputEnvelope[DriveRevisionsData]


# ─── drive.changes ────────────────────────────────────────────────────────────


class DriveChangesInput(BaseModel):
    """Input for ``drive.changes``: list Drive changes or get the start page token."""

    page_token: str | None = None


class DriveChangesData(BaseModel):
    """Data payload for ``drive.changes``.

    ``new_start_page_token`` is the baseline cursor to resume change tracking in
    a future session and stays in ``data`` as a domain cursor. Page-level
    continuation is surfaced via the envelope ``page.next_page_token``.
    """

    changes: list[dict[str, Any]]
    new_start_page_token: str | None = None


DriveChangesOutput = OutputEnvelope[DriveChangesData]


# ─── drive.changes_watch ──────────────────────────────────────────────────────


class DriveChangesWatchInput(BaseModel):
    """Input for ``drive.changes_watch``: register an HTTPS push-notification channel.

    Drive delivers change events to ``address`` (must be HTTPS). The channel
    is identified by ``channel_id`` and scoped to changes starting at
    ``page_token``. ``expiration_ms`` is an optional Unix-epoch millisecond
    timestamp; omit to let Drive choose the channel lifetime.

    Note: the HTTPS endpoint and channel identity must be provisioned by the
    operator before calling this op.
    """

    page_token: str = Field(description="Start page token for the change feed.")
    channel_id: str = Field(description="Unique channel ID assigned by the operator.")
    address: str = Field(description="HTTPS webhook URL that Drive will push to.")
    expiration_ms: int | None = Field(
        default=None,
        description="Optional channel expiration as Unix-epoch milliseconds.",
    )

    @field_validator("address")
    @classmethod
    def _require_https(cls, value: str) -> str:
        """Drive push channels must deliver to an HTTPS endpoint (audit Medium #4)."""
        if not value.strip().lower().startswith("https://"):
            raise ValueError(
                "drive.changes_watch address must be an https:// URL "
                f"(got {value!r})."
            )
        return value


class DriveChangesWatchData(BaseModel):
    """Data payload for ``drive.changes_watch`` (the registered channel resource)."""

    id: str
    resourceId: str
    resourceUri: str
    expiration: str | None = None


DriveChangesWatchOutput = OutputEnvelope[DriveChangesWatchData]
