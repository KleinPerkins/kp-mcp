"""Pydantic input / output models for all Gmail service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from google_kit.core.normalize import OutputEnvelope


class GmailListInput(BaseModel):
    """Input for ``gmail.list``: list recent messages."""

    q: str | None = Field(default=None, description="Gmail search query filter")
    label_ids: list[str] | None = Field(default=None, description="Label IDs to filter by")
    max_results: int = Field(default=25, ge=1, le=500)


class GmailMessageRef(BaseModel):
    """A minimal message reference (id + thread_id)."""

    id: str
    thread_id: str


class GmailListData(BaseModel):
    """Data payload for ``gmail.list``."""

    count: int
    messages: list[GmailMessageRef]


GmailListOutput = OutputEnvelope[GmailListData]


class GmailGetInput(BaseModel):
    """Input for ``gmail.get``: get a full message by ID."""

    message_id: str = Field(description="Gmail message ID")


class GmailGetData(BaseModel):
    """Data payload for ``gmail.get``."""

    id: str
    thread_id: str
    snippet: str
    subject: str
    from_: str = Field(alias="from_")
    date: str
    body: str
    label_ids: list[str]

    model_config = {"populate_by_name": True}


GmailGetOutput = OutputEnvelope[GmailGetData]


class GmailSearchInput(BaseModel):
    """Input for ``gmail.search``: search messages by Gmail query syntax."""

    q: str = Field(description="Gmail query string (e.g. 'from:boss@example.com')")
    max_results: int = Field(default=25, ge=1, le=500)


class GmailSearchData(BaseModel):
    """Data payload for ``gmail.search``."""

    query: str
    count: int
    messages: list[GmailMessageRef]


GmailSearchOutput = OutputEnvelope[GmailSearchData]


class GmailLabelsInput(BaseModel):
    """Input for ``gmail.labels``: list all labels."""


class GmailLabelItem(BaseModel):
    """One Gmail label entry."""

    id: str
    name: str
    label_type: str = Field(description="Label type: 'system' or 'user'")
    extra: dict[str, Any] = Field(default_factory=dict)


class GmailLabelsData(BaseModel):
    """Data payload for ``gmail.labels``."""

    count: int
    labels: list[GmailLabelItem]


GmailLabelsOutput = OutputEnvelope[GmailLabelsData]


class GmailProfileInput(BaseModel):
    """Input for ``gmail.profile``: get the authenticated user's Gmail profile."""


class GmailProfileData(BaseModel):
    """Data payload for ``gmail.profile``.

    emailAddress is redacted in all output — use the account identifier from
    the SecretStore / Keychain context rather than the API response.
    """

    email_address: str = Field(description="Always '[REDACTED]' — PII not emitted")
    messages_total: int
    threads_total: int


GmailProfileOutput = OutputEnvelope[GmailProfileData]


# --- gmail.history ---


class GmailHistoryInput(BaseModel):
    """Input for ``gmail.history``: list mailbox history since a given history ID."""

    start_history_id: str = Field(description="History ID to start listing from (exclusive)")
    history_types: list[str] | None = Field(
        default=None,
        description="Event types to include: messageAdded, messageDeleted, labelAdded, labelRemoved",
    )
    label_id: str | None = Field(default=None, description="Filter history by label ID")
    max_results: int = Field(default=100, ge=1, le=500)
    page_token: str | None = Field(default=None, description="Page token for continuation")


class GmailHistoryMessageRef(BaseModel):
    """Minimal message reference inside a history record."""

    id: str
    thread_id: str


class GmailHistoryRecord(BaseModel):
    """One history record entry."""

    id: str
    messages: list[GmailHistoryMessageRef] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class GmailHistoryData(BaseModel):
    """Data payload for ``gmail.history``.

    ``history_id`` is the mailbox watermark (the next ``start_history_id`` for a
    subsequent sync) and stays in ``data`` as a domain cursor. Page-level
    continuation is surfaced via the envelope ``page.next_page_token``.
    """

    history: list[GmailHistoryRecord]
    history_id: str | None = None


GmailHistoryOutput = OutputEnvelope[GmailHistoryData]


# --- gmail.attachments ---


class GmailAttachmentsInput(BaseModel):
    """Input for ``gmail.attachments``: get an attachment by message ID and attachment ID."""

    message_id: str = Field(description="Gmail message ID containing the attachment")
    attachment_id: str = Field(description="Attachment part ID (from message payload.parts[].body.attachmentId)")


class GmailAttachmentsData(BaseModel):
    """Data payload for ``gmail.attachments``."""

    attachment_id: str
    size: int
    data_b64: str = Field(description="URL-safe base64-encoded attachment content")


GmailAttachmentsOutput = OutputEnvelope[GmailAttachmentsData]


# --- gmail.draft ---


class GmailDraftInput(BaseModel):
    """Input for ``gmail.draft``: create a draft message."""

    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body_text: str = Field(description="Plain-text email body")
    cc: str | None = Field(default=None, description="CC recipient email address (optional)")


class GmailDraftData(BaseModel):
    """Data payload for ``gmail.draft``."""

    draft_id: str = Field(description="Gmail draft ID")
    message_id: str = Field(description="Draft's inner message ID")


GmailDraftOutput = OutputEnvelope[GmailDraftData]


# --- gmail.send ---


class GmailSendInput(BaseModel):
    """Input for ``gmail.send``: send an email message."""

    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body_text: str = Field(description="Plain-text email body")
    cc: str | None = Field(default=None, description="CC recipient email address (optional)")


class GmailSendData(BaseModel):
    """Data payload for ``gmail.send``."""

    message_id: str = Field(description="Sent message ID")
    thread_id: str = Field(description="Thread ID the message was placed in")
    label_ids: list[str] = Field(description="Label IDs applied to the sent message")


GmailSendOutput = OutputEnvelope[GmailSendData]


# --- gmail.modify ---


class GmailModifyInput(BaseModel):
    """Input for ``gmail.modify``: add or remove labels on a message."""

    message_id: str = Field(description="Gmail message ID to modify")
    add_label_ids: list[str] = Field(default_factory=list, description="Label IDs to add")
    remove_label_ids: list[str] = Field(default_factory=list, description="Label IDs to remove")


class GmailModifyData(BaseModel):
    """Data payload for ``gmail.modify``."""

    message_id: str = Field(description="Modified message ID")
    label_ids: list[str] = Field(description="Label IDs on the message after modification")


GmailModifyOutput = OutputEnvelope[GmailModifyData]


# --- gmail.manage_labels ---


class GmailManageLabelsInput(BaseModel):
    """Input for ``gmail.manage_labels``: create a Gmail label."""

    name: str = Field(description="Display name of the new label")
    label_list_visibility: str = Field(
        default="labelShow",
        description="Label visibility in the label list (labelShow | labelShowIfUnread | labelHide)",
    )
    message_list_visibility: str = Field(
        default="show",
        description="Message visibility in the message list (show | hide)",
    )


class GmailManageLabelData(BaseModel):
    """Data payload for ``gmail.manage_labels``."""

    label_id: str = Field(description="ID of the newly created label")
    name: str = Field(description="Display name of the created label")


GmailManageLabelOutput = OutputEnvelope[GmailManageLabelData]


# --- gmail.watch ---


class GmailWatchInput(BaseModel):
    """Input for ``gmail.watch``: start push notifications via Cloud Pub/Sub.

    Requires an operator-provisioned Cloud Pub/Sub topic with the Gmail service
    account granted publish access.
    """

    topic_name: str = Field(
        description="Fully-qualified Cloud Pub/Sub topic name "
                    "(e.g. projects/my-project/topics/gmail-watch)"
    )
    label_ids: list[str] | None = Field(
        default=None,
        description="Label IDs to watch (omit to watch all labels)",
    )
    label_filter_behavior: str | None = Field(
        default=None,
        description="Label filter behavior: include or exclude (omit for default)",
    )


class GmailWatchData(BaseModel):
    """Data payload for ``gmail.watch``."""

    history_id: str = Field(description="Current history ID at the time the watch was started")
    expiration: str = Field(description="Watch expiration timestamp (Unix ms string)")


GmailWatchOutput = OutputEnvelope[GmailWatchData]


# --- gmail.threads (users.threads.list; q optional => search) ---


class GmailThreadsInput(BaseModel):
    """Input for ``gmail.threads``: list (or search) Gmail threads.

    Calls ``users.threads.list``.  Providing ``q`` makes this op behave as a
    thread-level search using Gmail query syntax, so a single op covers both
    the threads.list and threads.list(query) capabilities.
    """

    q: str | None = Field(default=None, description="Gmail search query filter (e.g. 'from:boss@example.com')")
    label_ids: list[str] | None = Field(default=None, description="Label IDs to filter threads by")
    max_results: int = Field(default=25, ge=1, le=500, description="Maximum number of threads to return")
    page_token: str | None = Field(default=None, description="Page token for continuation (from a prior page.next_page_token)")


class GmailThreadRef(BaseModel):
    """A minimal thread reference as returned by ``users.threads.list``."""

    id: str = Field(description="Thread ID")
    snippet: str = Field(default="", description="Short snippet of the thread's latest message")
    history_id: str = Field(default="", description="History ID of the thread")


class GmailThreadsData(BaseModel):
    """Data payload for ``gmail.threads``."""

    count: int = Field(description="Number of threads returned on this page")
    threads: list[GmailThreadRef] = Field(description="Thread references (id + snippet + history_id)")


GmailThreadsOutput = OutputEnvelope[GmailThreadsData]


# --- gmail.thread_get (users.threads.get) ---


class GmailThreadGetInput(BaseModel):
    """Input for ``gmail.thread_get``: get a full thread (with messages) by ID."""

    thread_id: str = Field(description="Gmail thread ID")


class GmailThreadMessage(BaseModel):
    """One message inside a thread (mirrors ``gmail.get`` message shape)."""

    id: str = Field(description="Message ID")
    thread_id: str = Field(description="Thread ID the message belongs to")
    snippet: str = Field(default="", description="Short snippet of the message")
    subject: str = Field(default="", description="Subject header")
    from_: str = Field(default="", alias="from_", description="From header")
    date: str = Field(default="", description="Date header")
    body: str = Field(default="", description="Decoded plain-text body, truncated at 500 chars (BD-8)")
    label_ids: list[str] = Field(default_factory=list, description="Label IDs on the message")

    model_config = {"populate_by_name": True}


class GmailThreadGetData(BaseModel):
    """Data payload for ``gmail.thread_get``."""

    id: str = Field(description="Thread ID")
    history_id: str = Field(default="", description="History ID of the thread")
    snippet: str = Field(default="", description="Snippet of the thread's latest message")
    message_count: int = Field(description="Number of messages in the thread")
    messages: list[GmailThreadMessage] = Field(description="Messages in the thread, oldest first")


GmailThreadGetOutput = OutputEnvelope[GmailThreadGetData]


# --- gmail.batch_modify (users.messages.batchModify) ---


class GmailBatchModifyInput(BaseModel):
    """Input for ``gmail.batch_modify``: add/remove labels across many messages.

    Calls ``users.messages.batchModify`` (one request, many message IDs).
    Validates that ``ids`` is non-empty and that at least one of
    ``add_label_ids`` / ``remove_label_ids`` is provided.
    """

    ids: list[str] = Field(description="Message IDs to modify (must be non-empty)")
    add_label_ids: list[str] = Field(default_factory=list, description="Label IDs to add to every message")
    remove_label_ids: list[str] = Field(default_factory=list, description="Label IDs to remove from every message")

    @model_validator(mode="after")
    def _check_non_empty(self) -> "GmailBatchModifyInput":
        if not self.ids:
            raise ValueError("ids must contain at least one message ID")
        if not self.add_label_ids and not self.remove_label_ids:
            raise ValueError(
                "at least one of add_label_ids or remove_label_ids must be provided"
            )
        return self


class GmailBatchModifyData(BaseModel):
    """Data payload for ``gmail.batch_modify``.

    ``users.messages.batchModify`` returns HTTP 204 with an empty body on
    success, so the envelope is built from the validated request inputs.
    """

    modified_count: int = Field(description="Number of message IDs the label change was applied to")
    ids: list[str] = Field(description="Message IDs that were modified")
    add_label_ids: list[str] = Field(description="Label IDs added to every message")
    remove_label_ids: list[str] = Field(description="Label IDs removed from every message")


GmailBatchModifyOutput = OutputEnvelope[GmailBatchModifyData]
