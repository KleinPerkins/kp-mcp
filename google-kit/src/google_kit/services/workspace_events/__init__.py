"""Workspace Events service — registers 4 ops (eventing plane)."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    events_delete,
    events_list,
    events_patch,
    events_subscribe,
)
from .models import (
    EventsDeleteInput,
    EventsDeleteOutput,
    EventsListInput,
    EventsListOutput,
    EventsPatchInput,
    EventsPatchOutput,
    EventsSubscribeInput,
    EventsSubscribeOutput,
)

# Workspace Events subscriptions.{create,list,patch,delete} authorize using the
# TARGET resource's scope, not a dedicated events scope (none exists). The kit's
# events.* ops target Drive (§7), so drive.readonly is the authorizing scope — and
# it is already in the live consent union (core/auth.py:GOOGLE_KIT_SCOPES).
_DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"

#: Per-service F5 write gate (off by default). Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_EVENTS_WRITE_FLAG = "GOOGLE_KIT_ENABLE_EVENTS_WRITE"

register(OpSpec(
    name="events.subscribe",
    fn=events_subscribe,
    input_model=EventsSubscribeInput,
    output_model=EventsSubscribeOutput,
    posture="write",
    scopes=[_DRIVE_READONLY],
    perf={
        "api": "Workspace Events v1",
        "method": "subscriptions.create",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Subscribe to Drive file content-change events via Pub/Sub",
        "input": {
            "target_resource": "//drive.googleapis.com/files/<file-id>",
            "event_types": ["google.workspace.drive.file.v3.contentChanged"],
            "pubsub_topic": "projects/<project>/topics/<topic>",
        },
        "notes": (
            "Requires an operator-provisioned Cloud Pub/Sub topic; §7 covers Drive "
            "event targets only. A single-file target pairs with file-scoped events "
            "(e.g. contentChanged); container events (created/moved) need a folder or "
            "shared-drive target."
        ),
    }],
    plane="eventing",
    capability="eventing.subscriptions",
    flag=_EVENTS_WRITE_FLAG,
))

register(OpSpec(
    name="events.list",
    fn=events_list,
    input_model=EventsListInput,
    output_model=EventsListOutput,
    posture="read",
    scopes=[_DRIVE_READONLY],
    perf={
        "api": "Workspace Events v1",
        "method": "subscriptions.list",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List active subscriptions for a Drive target",
        "input": {
            "filter": "target_resource=\"//drive.googleapis.com/files/<file-id>\"",
        },
    }],
    plane="eventing",
    capability="eventing.subscriptions",
))

register(OpSpec(
    name="events.patch",
    fn=events_patch,
    input_model=EventsPatchInput,
    output_model=EventsPatchOutput,
    posture="write",
    scopes=[_DRIVE_READONLY],
    perf={
        "api": "Workspace Events v1",
        "method": "subscriptions.patch",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Extend a subscription TTL to one hour",
        "input": {
            "name": "subscriptions/<subscription-id>",
            "ttl": "3600s",
        },
    }],
    plane="eventing",
    capability="eventing.subscriptions",
    flag=_EVENTS_WRITE_FLAG,
))

register(OpSpec(
    name="events.delete",
    fn=events_delete,
    input_model=EventsDeleteInput,
    output_model=EventsDeleteOutput,
    posture="destructive",
    scopes=[_DRIVE_READONLY],
    perf={
        "api": "Workspace Events v1",
        "method": "subscriptions.delete",
        "quota": "varies",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Delete a subscription by name",
        "input": {"name": "subscriptions/<subscription-id>"},
    }],
    plane="eventing",
    capability="eventing.subscriptions",
    flag=_EVENTS_WRITE_FLAG,
))
