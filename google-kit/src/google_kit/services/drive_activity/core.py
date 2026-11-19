"""Core function for the Drive Activity service.

Parity coverage:
  drive_activity_query — mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
"""
from __future__ import annotations

from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope, PageInfo

from .models import (
    DriveActivityQueryData,
    DriveActivityQueryInput,
    DriveActivityQueryOutput,
)


def _wrap(data: Any, op: str, *, page: PageInfo | None = None) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, page=page, meta=Meta(op=op))


def _build_consolidation_strategy(value: str) -> dict[str, Any]:
    if value == "legacy":
        return {"consolidationStrategy": {"legacy": {}}}
    if value == "none":
        return {"consolidationStrategy": {"none": {}}}
    return {}


def drive_activity_query(
    inp: DriveActivityQueryInput,
    *,
    service: Any = None,
) -> DriveActivityQueryOutput:
    """Query Drive Activity v2 for file/folder activity events.

    Calls activity.query (POST) with an optional item or ancestor filter.
    At least one of item_name or ancestor_name should be provided.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(E2/E4)
    """
    body: dict[str, Any] = {}

    if inp.item_name is not None:
        body["itemName"] = inp.item_name
    if inp.ancestor_name is not None:
        body["ancestorName"] = inp.ancestor_name
    if inp.filter is not None:
        body["filter"] = inp.filter
    if inp.consolidation_strategy is not None:
        body.update(_build_consolidation_strategy(inp.consolidation_strategy))
    if inp.page_size is not None:
        body["pageSize"] = inp.page_size
    if inp.page_token is not None:
        body["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda: service.activity().query(body=body).execute(),
        op="drive_activity.query",
        posture="read",
    )
    payload = raw or {}
    data = DriveActivityQueryData(
        activities=payload.get("activities", []),
    )
    return _wrap(
        data,
        "drive_activity.query",
        page=PageInfo(next_page_token=payload.get("nextPageToken")),
    )
