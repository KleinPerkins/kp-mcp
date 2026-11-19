"""Core functions for the Workspace Events service (4 ops).

Parity coverage per op:

  events_subscribe — mutation-request DONE; sandbox-e2e DEFERRED
  events_list      — mock-read DONE; sandbox-e2e DEFERRED
  events_patch     — mutation-request DONE; sandbox-e2e DEFERRED
  events_delete    — request DONE; sandbox-e2e DEFERRED

Notes:
  - ``events_subscribe`` requires an operator-provisioned Cloud Pub/Sub topic;
    §7 covers Drive event targets only.
  - The ``events`` prefix maps to ``workspaceevents/v1`` via core/auth.py.
  - All write ops return a long-running Operation (name + done).
"""
from __future__ import annotations

from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope, PageInfo

from .models import (
    EventsDeleteData,
    EventsDeleteInput,
    EventsDeleteOutput,
    EventsListData,
    EventsListInput,
    EventsListOutput,
    EventsPatchData,
    EventsPatchInput,
    EventsPatchOutput,
    EventsSubscribeData,
    EventsSubscribeInput,
    EventsSubscribeOutput,
    EventsSubscriptionItem,
)


def _wrap(data: Any, op: str, *, page: PageInfo | None = None) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, page=page, meta=Meta(op=op))


# ─── events.subscribe ─────────────────────────────────────────────────────────


def events_subscribe(
    inp: EventsSubscribeInput,
    *,
    service: Any = None,
) -> EventsSubscribeOutput:
    """Create a Workspace Events subscription (returns a long-running Operation).

    Requires an operator-provisioned Cloud Pub/Sub topic; §7 covers Drive event
    targets only.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    body: dict[str, Any] = {
        "targetResource": inp.target_resource,
        "eventTypes": inp.event_types,
        "notificationEndpoint": {"pubsubTopic": inp.pubsub_topic},
    }
    if inp.payload_options is not None:
        body["payloadOptions"] = inp.payload_options

    raw = execute_api_call(
        lambda: service.subscriptions().create(body=body).execute(),
        op="events.subscribe",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.target_resource],
    )
    op_resp = raw or {}
    return _wrap(
        EventsSubscribeData(
            name=op_resp.get("name", ""),
            done=op_resp.get("done", False),
        ),
        "events.subscribe",
    )


# ─── events.list ──────────────────────────────────────────────────────────────


def events_list(
    inp: EventsListInput,
    *,
    service: Any = None,
) -> EventsListOutput:
    """List Workspace Events subscriptions matching a filter.

    Parity: mock-read DONE; sandbox-e2e DEFERRED
    """
    kwargs: dict[str, Any] = {"filter": inp.filter}
    if inp.page_size is not None:
        kwargs["pageSize"] = inp.page_size
    if inp.page_token is not None:
        kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda kw=dict(kwargs): service.subscriptions().list(**kw).execute(),
        op="events.list",
        posture="read",
    )
    resp = raw or {}
    items = [
        EventsSubscriptionItem(
            name=s.get("name", ""),
            target_resource=s.get("targetResource", ""),
            event_types=s.get("eventTypes", []),
            state=s.get("state", ""),
        )
        for s in resp.get("subscriptions", [])
    ]
    return _wrap(
        EventsListData(
            subscriptions=items,
        ),
        "events.list",
        page=PageInfo(next_page_token=resp.get("nextPageToken")),
    )


# ─── events.patch ─────────────────────────────────────────────────────────────


def events_patch(
    inp: EventsPatchInput,
    *,
    service: Any = None,
) -> EventsPatchOutput:
    """Update a Workspace Events subscription (e.g. extend TTL).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED
    """
    body: dict[str, Any] = {}
    if inp.ttl is not None:
        body["ttl"] = inp.ttl

    raw = execute_api_call(
        lambda: service.subscriptions().patch(
            name=inp.name,
            updateMask=inp.update_mask,
            body=body,
        ).execute(),
        op="events.patch",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.name],
    )
    op_resp = raw or {}
    return _wrap(
        EventsPatchData(
            name=op_resp.get("name", inp.name),
            done=op_resp.get("done", False),
        ),
        "events.patch",
    )


# ─── events.delete ────────────────────────────────────────────────────────────


def events_delete(
    inp: EventsDeleteInput,
    *,
    service: Any = None,
) -> EventsDeleteOutput:
    """Delete a Workspace Events subscription.

    Parity: request DONE; sandbox-e2e DEFERRED
    """
    raw = execute_api_call(
        lambda: service.subscriptions().delete(name=inp.name).execute(),
        op="events.delete",
        posture="destructive",
        normalized_request=inp.model_dump(),
        target_ids=[inp.name],
    )
    op_resp = raw or {}
    return _wrap(
        EventsDeleteData(
            name=op_resp.get("name", inp.name),
            done=op_resp.get("done", False),
        ),
        "events.delete",
    )
