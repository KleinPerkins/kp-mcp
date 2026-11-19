"""Pydantic input / output models for all Tasks service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope


class TasksListListsInput(BaseModel):
    """Input for ``tasks.list_lists``: list all task lists."""

    max_results: int = Field(default=100, ge=1, le=100)
    page_token: str | None = Field(
        default=None, description="Continuation token from a prior page.next_page_token"
    )


class TaskListItem(BaseModel):
    """One task list entry."""

    id: str
    title: str
    kind: str = "tasks#taskList"
    updated: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class TasksListListsData(BaseModel):
    """Data payload for ``tasks.list_lists``."""

    count: int
    task_lists: list[TaskListItem]


TasksListListsOutput = OutputEnvelope[TasksListListsData]


class TasksListInput(BaseModel):
    """Input for ``tasks.list``: list tasks in a task list."""

    tasklist: str = Field(default="@default")
    max_results: int = Field(default=100, ge=1, le=100)
    show_completed: bool = False
    due_min: str | None = None
    due_max: str | None = None
    page_token: str | None = Field(
        default=None, description="Continuation token from a prior page.next_page_token"
    )


class TaskItem(BaseModel):
    """One task entry."""

    id: str
    title: str
    status: str = "needsAction"
    due: str | None = None
    notes: str | None = None
    kind: str = "tasks#task"
    extra: dict[str, Any] = Field(default_factory=dict)


class TasksListData(BaseModel):
    """Data payload for ``tasks.list``."""

    count: int
    tasks: list[TaskItem]


TasksListOutput = OutputEnvelope[TasksListData]


class TasksCreateInput(BaseModel):
    """Input for ``tasks.create``: create a new task."""

    title: str
    tasklist: str = Field(default="@default")
    notes: str | None = None
    due: str | None = None


class TasksCreateData(BaseModel):
    """Data payload for ``tasks.create``."""

    id: str
    title: str
    status: str
    due: str | None = None


TasksCreateOutput = OutputEnvelope[TasksCreateData]


class TasksCompleteInput(BaseModel):
    """Input for ``tasks.complete``: mark a task as completed."""

    task_id: str
    tasklist: str = Field(default="@default")


class TasksCompleteData(BaseModel):
    """Data payload for ``tasks.complete``."""

    id: str
    title: str
    status: str


TasksCompleteOutput = OutputEnvelope[TasksCompleteData]


class TasksUpdateInput(BaseModel):
    """Input for ``tasks.update``: update title, notes, due date, or status."""

    task_id: str
    tasklist: str = Field(default="@default")
    title: str | None = None
    notes: str | None = None
    due: str | None = None
    status: str | None = None


class TasksUpdateData(BaseModel):
    """Data payload for ``tasks.update``."""

    id: str
    title: str
    status: str
    due: str | None = None


TasksUpdateOutput = OutputEnvelope[TasksUpdateData]


class TasksDeleteInput(BaseModel):
    """Input for ``tasks.delete``: permanently delete a task."""

    task_id: str
    tasklist: str = Field(default="@default")


class TasksDeleteData(BaseModel):
    """Data payload for ``tasks.delete``."""

    deleted: bool
    task_id: str


TasksDeleteOutput = OutputEnvelope[TasksDeleteData]
