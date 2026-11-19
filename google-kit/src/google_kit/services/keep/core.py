"""Core functions for the Keep service (cutover-minimum: 4 ops).

Transport: official Keep REST API v1 (keep.googleapis.com), accessed via
``googleapiclient.discovery.build("keep", "v1")``.  The legacy ``gkeep.py``
uses ``build_service("keep", "v1", creds)`` throughout — this is transport
path (a), compatible with the standard MockGoogleService pattern.

Keep API availability note: the Keep API requires a Google Workspace account
with domain-admin enablement.  Personal accounts receive 403/404.  Auth and
sandbox provisioning are DEFERRED(P6); see ``keep_sandbox_availability`` in
COVERAGE.md.  If the API is not available, callers receive an informative
error with the fallback suggestion: ``google-kit drive create --type doc``.

Parity coverage per op:

  keep_list    — mock-read DONE; sandbox-e2e DEFERRED(P6)
  keep_get     — mock-read DONE; sandbox-e2e DEFERRED(P6)
  keep_create  — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  keep_delete  — mutation-request DONE; sandbox-e2e DEFERRED(P6)

Legacy quirks preserved:
  - ``notes().list`` uses ``pageSize`` (legacy --limit default 50) and
    ``filter`` (empty string when not provided, matching legacy behavior).
  - ``notes().delete`` trashes the note (not permanent deletion) — this is
    the Keep API's only delete mechanism.
  - Create body matches legacy exactly: text body → ``body.text.text``;
    list body → ``body.list.listItems`` with each item as ``{"text": {"text": item}}``.
"""
from __future__ import annotations

from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope

from .models import (
    KeepCreateData,
    KeepCreateInput,
    KeepCreateOutput,
    KeepDeleteData,
    KeepDeleteInput,
    KeepDeleteOutput,
    KeepGetData,
    KeepGetInput,
    KeepGetOutput,
    KeepListData,
    KeepListInput,
    KeepListOutput,
    NoteItem,
)

_KEEP_SCOPE = "https://www.googleapis.com/auth/keep"


def _extract_body_text(body: dict[str, Any]) -> str | None:
    """Extract plain-text content from a Keep note body dict, or None."""
    if not body:
        return None
    text_content = body.get("text")
    if text_content and isinstance(text_content, dict):
        return text_content.get("text") or None
    return None


def _wrap(data: Any, op: str) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, meta=Meta(op=op))


def _note_to_item(raw: dict[str, Any]) -> NoteItem:
    return NoteItem(
        name=raw.get("name", ""),
        title=raw.get("title", ""),
        body_text=_extract_body_text(raw.get("body", {})),
        create_time=raw.get("createTime"),
        update_time=raw.get("updateTime"),
    )


def keep_list(
    inp: KeepListInput,
    *,
    service: Any = None,
) -> KeepListOutput:
    """List Keep notes.

    Legacy quirks: pageSize defaults to 50 (matching legacy --limit default);
    filter is passed as empty string when not provided.

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.notes().list(
            pageSize=inp.page_size,
            filter=inp.filter or "",
        ).execute(),
        op="keep.list",
        posture="read",
    )
    notes_raw = (raw or {}).get("notes", [])
    notes = [_note_to_item(n) for n in notes_raw]
    return _wrap(KeepListData(count=len(notes), notes=notes), "keep.list")


def keep_get(
    inp: KeepGetInput,
    *,
    service: Any = None,
) -> KeepGetOutput:
    """Get a single Keep note by resource name (e.g. 'notes/abc123').

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.notes().get(name=inp.note_id).execute(),
        op="keep.get",
        posture="read",
    )
    note = raw or {}
    return _wrap(
        KeepGetData(
            name=note.get("name", ""),
            title=note.get("title", ""),
            body_text=_extract_body_text(note.get("body", {})),
            create_time=note.get("createTime"),
            update_time=note.get("updateTime"),
        ),
        "keep.get",
    )


def keep_create(
    inp: KeepCreateInput,
    *,
    service: Any = None,
) -> KeepCreateOutput:
    """Create a new Keep note (text or checklist).

    Body construction matches legacy ``gkeep.py cmd_create`` exactly:
      - Text note: ``body = {"title": title, "body": {"text": {"text": body_text}}}``
      - List note: ``body = {"title": title, "body": {"list": {"listItems": [{"text": {"text": item}} ...]}}}``
      - No body_text and no list_items: ``body = {"title": title, "body": {}}``

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    body: dict[str, Any] = {
        "title": inp.title,
        "body": {"text": {"text": inp.body_text}} if inp.body_text else {},
    }

    if inp.list_items:
        parsed = [item.strip() for item in inp.list_items.split(",")]
        body["body"] = {
            "list": {
                "listItems": [{"text": {"text": item}} for item in parsed],
            }
        }

    raw = execute_api_call(
        lambda: service.notes().create(body=body).execute(),
        op="keep.create",
        posture="write",
        # body_text / list_items are note content, not a mutation target.
        normalized_request=inp.model_dump(exclude={"body_text", "list_items"}),
        # The created note's id lives only in its resource-path ``name`` (e.g.
        # ``notes/<id>``), which the top-level ``*Id`` heuristic excludes; extract
        # it post-call so the audit trail can identify the mutated note.
        target_ids=lambda created: (
            [created["name"]]
            if isinstance(created, dict) and created.get("name")
            else []
        ),
    )
    created = raw or {}
    return _wrap(
        KeepCreateData(
            name=created.get("name", ""),
            title=created.get("title", inp.title),
        ),
        "keep.create",
    )


def keep_delete(
    inp: KeepDeleteInput,
    *,
    service: Any = None,
) -> KeepDeleteOutput:
    """Trash a Keep note (delete = trash, not permanent, matching legacy gkeep.py).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    execute_api_call(
        lambda: service.notes().delete(name=inp.note_id).execute(),
        op="keep.delete",
        posture="destructive",
        normalized_request=inp.model_dump(),
        target_ids=[inp.note_id],
    )
    return _wrap(KeepDeleteData(deleted=True, note_id=inp.note_id), "keep.delete")
