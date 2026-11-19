"""Tasks service — registers 6 cutover-minimum ops in the google-kit registry."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    tasks_complete,
    tasks_create,
    tasks_delete,
    tasks_list,
    tasks_list_lists,
    tasks_update,
)
from .models import (
    TasksCompleteInput,
    TasksCompleteOutput,
    TasksCreateInput,
    TasksCreateOutput,
    TasksDeleteInput,
    TasksDeleteOutput,
    TasksListInput,
    TasksListListsInput,
    TasksListListsOutput,
    TasksListOutput,
    TasksUpdateInput,
    TasksUpdateOutput,
)

_TASKS_SCOPES = ["https://www.googleapis.com/auth/tasks"]
_TASKS_READONLY_SCOPES = ["https://www.googleapis.com/auth/tasks.readonly"]

#: Per-service F5 write gate (off by default). Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_TASKS_WRITE_FLAG = "GOOGLE_KIT_ENABLE_TASKS_WRITE"

register(OpSpec(
    name="tasks.list_lists",
    fn=tasks_list_lists,
    input_model=TasksListListsInput,
    output_model=TasksListListsOutput,
    posture="read",
    scopes=_TASKS_READONLY_SCOPES,
    perf={"api": "Tasks v1", "method": "tasklists.list", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List all task lists",
        "input": {"max_results": 100},
        "cli": "google-kit tasks list-lists",
    }],
))

register(OpSpec(
    name="tasks.list",
    fn=tasks_list,
    input_model=TasksListInput,
    output_model=TasksListOutput,
    posture="read",
    scopes=_TASKS_READONLY_SCOPES,
    perf={"api": "Tasks v1", "method": "tasks.list", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List tasks in the default task list",
        "input": {"tasklist": "@default", "max_results": 100, "show_completed": False},
        "cli": "google-kit tasks list --tasklist @default",
    }],
))

register(OpSpec(
    name="tasks.create",
    fn=tasks_create,
    input_model=TasksCreateInput,
    output_model=TasksCreateOutput,
    posture="write",
    scopes=_TASKS_SCOPES,
    perf={"api": "Tasks v1", "method": "tasks.insert", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a task with a due date",
        "input": {"title": "Buy milk", "tasklist": "@default", "due": "2025-01-15"},
        "cli": "google-kit tasks create 'Buy milk' --due 2025-01-15",
    }],
    flag=_TASKS_WRITE_FLAG,
))

register(OpSpec(
    name="tasks.complete",
    fn=tasks_complete,
    input_model=TasksCompleteInput,
    output_model=TasksCompleteOutput,
    posture="write",
    scopes=_TASKS_SCOPES,
    perf={"api": "Tasks v1", "method": "tasks.get + tasks.update", "quota": "1000 req/day (2 calls)"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Mark a task as completed",
        "input": {"task_id": "<task-id>", "tasklist": "@default"},
        "cli": "google-kit tasks complete <task-id>",
    }],
    flag=_TASKS_WRITE_FLAG,
))

register(OpSpec(
    name="tasks.update",
    fn=tasks_update,
    input_model=TasksUpdateInput,
    output_model=TasksUpdateOutput,
    posture="write",
    scopes=_TASKS_SCOPES,
    perf={"api": "Tasks v1", "method": "tasks.get + tasks.update", "quota": "1000 req/day (2 calls)"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Update a task's title and due date",
        "input": {"task_id": "<task-id>", "title": "New title", "due": "2025-02-01"},
        "cli": "google-kit tasks update <task-id> --title 'New title' --due 2025-02-01",
    }],
    flag=_TASKS_WRITE_FLAG,
))

register(OpSpec(
    name="tasks.delete",
    fn=tasks_delete,
    input_model=TasksDeleteInput,
    output_model=TasksDeleteOutput,
    posture="destructive",
    scopes=_TASKS_SCOPES,
    perf={"api": "Tasks v1", "method": "tasks.delete", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Delete a task permanently",
        "input": {"task_id": "<task-id>", "tasklist": "@default"},
        "cli": "google-kit tasks delete <task-id>",
    }],
    flag=_TASKS_WRITE_FLAG,
))
