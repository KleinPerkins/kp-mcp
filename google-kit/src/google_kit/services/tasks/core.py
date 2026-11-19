"""Core functions for the Tasks service (cutover-minimum: 6 ops).

Parity coverage per op:

  tasks_list_lists  — mock-read DONE; sandbox-e2e DEFERRED(P6)
  tasks_list        — mock-read DONE; sandbox-e2e DEFERRED(P6)
  tasks_create      — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  tasks_complete    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  tasks_update      — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  tasks_delete      — mutation-request DONE; sandbox-e2e DEFERRED(P6)

Legacy quirks preserved:
  - maxResults=100 hardcoded for list_lists; list uses configurable max_results
    (default 100) matching legacy's --limit default.
  - showCompleted=True also sets showHidden=True (same as legacy).
  - due date coercion: YYYY-MM-DD → <date>T00:00:00.000Z (midnight UTC);
    ISO datetime → normalized to UTC with same format.  Matches _parse_due
    in legacy gtasks.py.
  - tasks_complete / tasks_update use GET-then-PUT full resource update.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope, PageInfo

from .models import (
    TaskItem,
    TaskListItem,
    TasksCompleteData,
    TasksCompleteInput,
    TasksCompleteOutput,
    TasksCreateData,
    TasksCreateInput,
    TasksCreateOutput,
    TasksDeleteData,
    TasksDeleteInput,
    TasksDeleteOutput,
    TasksListData,
    TasksListInput,
    TasksListListsData,
    TasksListListsInput,
    TasksListListsOutput,
    TasksListOutput,
    TasksUpdateData,
    TasksUpdateInput,
    TasksUpdateOutput,
)

_TASKS_SCOPES = ["https://www.googleapis.com/auth/tasks"]


def _coerce_due(value: str) -> str:
    """Coerce a due-date string to midnight-UTC RFC 3339 format.

    Matches legacy ``_parse_due`` in ``gtasks.py``:
      - If ``T`` present: parse as ISO datetime → UTC → ``%Y-%m-%dT%H:%M:%S.000Z``.
      - Otherwise: append ``T00:00:00.000Z``.
    """
    value = value.strip()
    if "T" in value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        except (ValueError, TypeError):
            return value if value.endswith("Z") else value + "Z"
    return f"{value}T00:00:00.000Z"


def _wrap(data: Any, op: str, *, page: PageInfo | None = None) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, page=page, meta=Meta(op=op))


def tasks_list_lists(
    inp: TasksListListsInput,
    *,
    service: Any = None,
) -> TasksListListsOutput:
    """List all task lists (maxResults=100, matching legacy default).

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.tasklists().list(
            maxResults=inp.max_results,
            pageToken=inp.page_token or None,
        ).execute(),
        op="tasks.list_lists",
        posture="read",
    )
    payload = raw or {}
    items = payload.get("items", [])
    task_lists = [
        TaskListItem(
            id=tl.get("id", ""),
            title=tl.get("title", ""),
            kind=tl.get("kind", "tasks#taskList"),
            updated=tl.get("updated"),
        )
        for tl in items
    ]
    return _wrap(
        TasksListListsData(count=len(task_lists), task_lists=task_lists),
        "tasks.list_lists",
        page=PageInfo(next_page_token=payload.get("nextPageToken")),
    )


def tasks_list(
    inp: TasksListInput,
    *,
    service: Any = None,
) -> TasksListOutput:
    """List tasks in a task list.

    Legacy quirks:
      - showCompleted also sets showHidden=True.
      - maxResults default 100 (matches legacy --limit default).

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    kwargs: dict[str, Any] = {
        "tasklist": inp.tasklist,
        "maxResults": inp.max_results,
        "showCompleted": inp.show_completed,
        "showHidden": inp.show_completed,
    }
    if inp.due_min:
        kwargs["dueMin"] = _coerce_due(inp.due_min)
    if inp.due_max:
        kwargs["dueMax"] = _coerce_due(inp.due_max)
    if inp.page_token:
        kwargs["pageToken"] = inp.page_token

    raw = execute_api_call(
        lambda: service.tasks().list(**kwargs).execute(),
        op="tasks.list",
        posture="read",
    )
    payload = raw or {}
    items = payload.get("items", [])
    tasks = [
        TaskItem(
            id=t.get("id", ""),
            title=t.get("title", ""),
            status=t.get("status", "needsAction"),
            due=t.get("due"),
            notes=t.get("notes"),
            kind=t.get("kind", "tasks#task"),
        )
        for t in items
    ]
    return _wrap(
        TasksListData(count=len(tasks), tasks=tasks),
        "tasks.list",
        page=PageInfo(next_page_token=payload.get("nextPageToken")),
    )


def tasks_create(
    inp: TasksCreateInput,
    *,
    service: Any = None,
) -> TasksCreateOutput:
    """Create a new task.

    Due date coercion: YYYY-MM-DD → <date>T00:00:00.000Z (midnight UTC).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    body: dict[str, Any] = {"title": inp.title}
    if inp.notes:
        body["notes"] = inp.notes
    if inp.due:
        body["due"] = _coerce_due(inp.due)

    raw = execute_api_call(
        lambda: service.tasks().insert(tasklist=inp.tasklist, body=body).execute(),
        op="tasks.create",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    created = raw or {}
    return _wrap(
        TasksCreateData(
            id=created.get("id", ""),
            title=created.get("title", inp.title),
            status=created.get("status", "needsAction"),
            due=created.get("due"),
        ),
        "tasks.create",
    )


def tasks_complete(
    inp: TasksCompleteInput,
    *,
    service: Any = None,
) -> TasksCompleteOutput:
    """Mark a task as completed (GET-then-PUT full resource update).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    task = execute_api_call(
        lambda: service.tasks().get(tasklist=inp.tasklist, task=inp.task_id).execute(),
        op="tasks.complete.get",
        posture="read",
    )
    task = dict(task or {})
    task["status"] = "completed"

    updated = execute_api_call(
        lambda: service.tasks().update(
            tasklist=inp.tasklist, task=inp.task_id, body=task
        ).execute(),
        op="tasks.complete",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.task_id],
    )
    result = updated or {}
    return _wrap(
        TasksCompleteData(
            id=result.get("id", inp.task_id),
            title=result.get("title", ""),
            status=result.get("status", "completed"),
        ),
        "tasks.complete",
    )


def tasks_update(
    inp: TasksUpdateInput,
    *,
    service: Any = None,
) -> TasksUpdateOutput:
    """Update a task's title, notes, due date, or status (GET-then-PUT).

    Due date coercion applied when due is provided.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    task = execute_api_call(
        lambda: service.tasks().get(tasklist=inp.tasklist, task=inp.task_id).execute(),
        op="tasks.update.get",
        posture="read",
    )
    task = dict(task or {})

    if inp.title is not None:
        task["title"] = inp.title
    if inp.notes is not None:
        task["notes"] = inp.notes
    if inp.due is not None:
        task["due"] = _coerce_due(inp.due)
    if inp.status is not None:
        task["status"] = inp.status

    updated = execute_api_call(
        lambda: service.tasks().update(
            tasklist=inp.tasklist, task=inp.task_id, body=task
        ).execute(),
        op="tasks.update",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.task_id],
    )
    result = updated or {}
    return _wrap(
        TasksUpdateData(
            id=result.get("id", inp.task_id),
            title=result.get("title", ""),
            status=result.get("status", "needsAction"),
            due=result.get("due"),
        ),
        "tasks.update",
    )


def tasks_delete(
    inp: TasksDeleteInput,
    *,
    service: Any = None,
) -> TasksDeleteOutput:
    """Permanently delete a task.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    execute_api_call(
        lambda: service.tasks().delete(
            tasklist=inp.tasklist, task=inp.task_id
        ).execute(),
        op="tasks.delete",
        posture="destructive",
        normalized_request=inp.model_dump(),
        target_ids=[inp.task_id],
    )
    return _wrap(TasksDeleteData(deleted=True, task_id=inp.task_id), "tasks.delete")
