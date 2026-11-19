"""Pydantic input / output models for all Workspace Events service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope

# ─── events.subscribe ─────────────────────────────────────────────────────────


class EventsSubscribeInput(BaseModel):
    """Input for ``events.subscribe``: create a Workspace Events subscription.

    Requires an operator-provisioned Cloud Pub/Sub topic; §7 covers Drive event
    targets only.
    """

    target_resource: str = Field(
        description="Full resource name of the Drive target, e.g. a file "
        "'//drive.googleapis.com/files/<id>' or shared drive "
        "'//drive.googleapis.com/drives/<id>'."
    )
    event_types: list[str] = Field(
        description="List of Drive event type strings (CloudEvents format "
        "google.workspace.drive.RESOURCE.v3.ACTION), e.g. "
        "['google.workspace.drive.file.v3.contentChanged']. Valid file actions: "
        "created, moved, contentChanged, deleted, trashed, untrashed, renamed. The "
        "event must match the target: a single-file target supports file-scoped "
        "events (e.g. contentChanged); container events (created/moved) require a "
        "folder or shared-drive target."
    )
    pubsub_topic: str = Field(
        description="Fully-qualified Pub/Sub topic name, e.g. "
        "'projects/<project>/topics/<topic>'."
    )
    payload_options: dict[str, Any] | None = Field(
        default=None,
        description="Optional payloadOptions object to control event payload shape.",
    )


class EventsSubscribeData(BaseModel):
    """Data payload for ``events.subscribe`` (long-running Operation)."""

    name: str
    done: bool = False


EventsSubscribeOutput = OutputEnvelope[EventsSubscribeData]


# ─── events.list ──────────────────────────────────────────────────────────────


class EventsListInput(BaseModel):
    """Input for ``events.list``: list Workspace Events subscriptions."""

    filter: str = Field(
        description="Filter string, e.g. "
        "'target_resource=\"//drive.googleapis.com/files/<file-id>\"'."
    )
    page_size: int | None = Field(default=None, description="Max subscriptions to return.")
    page_token: str | None = Field(default=None, description="Continuation token.")


class EventsSubscriptionItem(BaseModel):
    """One subscription entry returned by ``events.list``."""

    name: str
    target_resource: str = ""
    event_types: list[str] = Field(default_factory=list)
    state: str = ""


class EventsListData(BaseModel):
    """Data payload for ``events.list``."""

    subscriptions: list[EventsSubscriptionItem]


EventsListOutput = OutputEnvelope[EventsListData]


# ─── events.patch ─────────────────────────────────────────────────────────────


class EventsPatchInput(BaseModel):
    """Input for ``events.patch``: update a Workspace Events subscription TTL."""

    name: str = Field(description="Subscription resource name to patch.")
    update_mask: str = Field(default="ttl", description="Comma-separated field mask.")
    ttl: str | None = Field(
        default=None, description="New TTL duration string, e.g. '3600s'."
    )


class EventsPatchData(BaseModel):
    """Data payload for ``events.patch`` (long-running Operation)."""

    name: str
    done: bool = False


EventsPatchOutput = OutputEnvelope[EventsPatchData]


# ─── events.delete ────────────────────────────────────────────────────────────


class EventsDeleteInput(BaseModel):
    """Input for ``events.delete``: delete a Workspace Events subscription."""

    name: str = Field(description="Subscription resource name to delete.")


class EventsDeleteData(BaseModel):
    """Data payload for ``events.delete`` (long-running Operation or empty)."""

    name: str
    done: bool = False


EventsDeleteOutput = OutputEnvelope[EventsDeleteData]
