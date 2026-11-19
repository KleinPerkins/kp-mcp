"""Tests for the Tasks reference service.

Note on registry isolation: ``test_registry.py`` clears ``_REGISTRY`` during
its own tests.  The module-scoped ``_ensure_tasks`` fixture below re-registers
Tasks ops if needed so these tests remain order-independent.

Coverage:
  tasks_list_lists   — mock-read parity (normalized-json)
  tasks_list         — mock-read parity (normalized-json)
  tasks_create       — mutation-request parity
  tasks_complete     — mutation-request parity (GET-then-PUT; status=completed)
  tasks_update       — mutation-request parity (GET-then-PUT; field update + due coercion)
  tasks_delete       — mutation-request parity (no body; confirmed delete flag)

Parity status per op:
  tasks_list_lists  — mock-read DONE; sandbox-e2e DEFERRED(P6)
  tasks_list        — mock-read DONE; sandbox-e2e DEFERRED(P6)
  tasks_create      — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  tasks_complete    — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  tasks_update      — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  tasks_delete      — mutation-request DONE; sandbox-e2e DEFERRED(P6)
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from kp_mcp_testkit.mock_google import MockGoogleService
from kp_mcp_testkit.parity import compare


@pytest.fixture(autouse=True, scope="module")
def _ensure_tasks(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Re-register Tasks ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.tasks as tasks_mod

    if "tasks.list_lists" not in {s.name for s in reg.all_specs()}:
        importlib.reload(tasks_mod)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "tasks"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _raw_task_stub() -> dict:
    return {
        "id": "task001",
        "kind": "tasks#task",
        "title": "Buy milk",
        "status": "needsAction",
    }


class TestTasksListLists:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.tasks.core import tasks_list_lists
        from google_kit.services.tasks.models import TasksListListsInput

        response = _load("list_lists_response.json")
        expected = _load("list_lists_expected.json")

        svc = MockGoogleService(responses={("tasklists", "list"): response})
        result = tasks_list_lists(TasksListListsInput(), service=svc)

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_empty_list(self) -> None:
        from google_kit.services.tasks.core import tasks_list_lists
        from google_kit.services.tasks.models import TasksListListsInput

        svc = MockGoogleService(responses={("tasklists", "list"): {"items": []}})
        result = tasks_list_lists(TasksListListsInput(), service=svc)
        assert result.data.count == 0
        assert result.data.task_lists == []

    def test_maxresults_100_hardcoded(self) -> None:
        from google_kit.services.tasks.core import tasks_list_lists
        from google_kit.services.tasks.models import TasksListListsInput

        svc = MockGoogleService(responses={("tasklists", "list"): {"items": []}})
        tasks_list_lists(TasksListListsInput(), service=svc)
        req = svc.get_requests()[0]
        assert req.kwargs.get("maxResults") == 100

    def test_next_page_token_surfaced_in_page(self) -> None:
        from google_kit.services.tasks.core import tasks_list_lists
        from google_kit.services.tasks.models import TasksListListsInput

        svc = MockGoogleService(
            responses={("tasklists", "list"): {"items": [], "nextPageToken": "NEXT2"}}
        )
        result = tasks_list_lists(TasksListListsInput(), service=svc)
        assert result.page is not None
        assert result.page.next_page_token == "NEXT2"

    def test_page_token_forwarded(self) -> None:
        from google_kit.services.tasks.core import tasks_list_lists
        from google_kit.services.tasks.models import TasksListListsInput

        svc = MockGoogleService(responses={("tasklists", "list"): {"items": []}})
        tasks_list_lists(TasksListListsInput(page_token="PREV"), service=svc)
        req = svc.get_requests()[0]
        assert req.kwargs.get("pageToken") == "PREV"

    def test_no_next_page_token_is_none(self) -> None:
        from google_kit.services.tasks.core import tasks_list_lists
        from google_kit.services.tasks.models import TasksListListsInput

        svc = MockGoogleService(responses={("tasklists", "list"): {"items": []}})
        result = tasks_list_lists(TasksListListsInput(), service=svc)
        assert result.page is not None
        assert result.page.next_page_token is None


class TestTasksList:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.tasks.core import tasks_list
        from google_kit.services.tasks.models import TasksListInput

        response = _load("list_response.json")
        expected = _load("list_expected.json")

        svc = MockGoogleService(responses={("tasks", "list"): response})
        result = tasks_list(TasksListInput(tasklist="@default"), service=svc)

        actual_tasks = [t.model_dump() for t in result.data.tasks]
        expected_tasks = expected["tasks"]
        parity = compare("normalized-json", expected_tasks, actual_tasks)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"
        assert result.data.count == 2

    def test_show_completed_sets_hidden(self) -> None:
        from google_kit.services.tasks.core import tasks_list
        from google_kit.services.tasks.models import TasksListInput

        svc = MockGoogleService(responses={("tasks", "list"): {"items": []}})
        tasks_list(TasksListInput(show_completed=True), service=svc)
        req = svc.get_requests()[0]
        assert req.kwargs.get("showCompleted") is True
        assert req.kwargs.get("showHidden") is True

    def test_due_filter_coercion(self) -> None:
        from google_kit.services.tasks.core import tasks_list
        from google_kit.services.tasks.models import TasksListInput

        svc = MockGoogleService(responses={("tasks", "list"): {"items": []}})
        tasks_list(
            TasksListInput(due_min="2024-01-01", due_max="2024-12-31"),
            service=svc,
        )
        req = svc.get_requests()[0]
        assert req.kwargs["dueMin"] == "2024-01-01T00:00:00.000Z"
        assert req.kwargs["dueMax"] == "2024-12-31T00:00:00.000Z"

    def test_next_page_token_surfaced_in_page(self) -> None:
        from google_kit.services.tasks.core import tasks_list
        from google_kit.services.tasks.models import TasksListInput

        svc = MockGoogleService(
            responses={("tasks", "list"): {"items": [], "nextPageToken": "PAGE2"}}
        )
        result = tasks_list(TasksListInput(), service=svc)
        assert result.page is not None
        assert result.page.next_page_token == "PAGE2"

    def test_page_token_forwarded(self) -> None:
        from google_kit.services.tasks.core import tasks_list
        from google_kit.services.tasks.models import TasksListInput

        svc = MockGoogleService(responses={("tasks", "list"): {"items": []}})
        tasks_list(TasksListInput(page_token="CURSOR"), service=svc)
        req = svc.get_requests()[0]
        assert req.kwargs.get("pageToken") == "CURSOR"

    def test_no_page_token_not_forwarded(self) -> None:
        from google_kit.services.tasks.core import tasks_list
        from google_kit.services.tasks.models import TasksListInput

        svc = MockGoogleService(responses={("tasks", "list"): {"items": []}})
        tasks_list(TasksListInput(), service=svc)
        req = svc.get_requests()[0]
        assert "pageToken" not in req.kwargs


class TestTasksCreate:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.tasks.core import tasks_create
        from google_kit.services.tasks.models import TasksCreateInput

        expected_body = _load("create_expected_body.json")
        canned_response = {
            "id": "new001",
            "title": "Buy milk",
            "status": "needsAction",
            "due": "2025-01-15T00:00:00.000Z",
        }
        svc = MockGoogleService(responses={("tasks", "insert"): canned_response})
        tasks_create(
            TasksCreateInput(
                title="Buy milk",
                notes="Pick up semi-skimmed",
                due="2025-01-15",
                tasklist="@default",
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_due_date_midnight_utc(self) -> None:
        from google_kit.services.tasks.core import tasks_create
        from google_kit.services.tasks.models import TasksCreateInput

        svc = MockGoogleService(responses={("tasks", "insert"): {"id": "x", "title": "t", "status": "needsAction"}})
        tasks_create(TasksCreateInput(title="t", due="2025-06-15"), service=svc)
        body = svc.last_request_body()
        assert body is not None
        assert body["due"] == "2025-06-15T00:00:00.000Z"

    def test_no_due_no_notes(self) -> None:
        from google_kit.services.tasks.core import tasks_create
        from google_kit.services.tasks.models import TasksCreateInput

        svc = MockGoogleService(responses={("tasks", "insert"): {"id": "x", "title": "t", "status": "needsAction"}})
        tasks_create(TasksCreateInput(title="Just a task"), service=svc)
        body = svc.last_request_body()
        assert "due" not in body
        assert "notes" not in body


class TestTasksComplete:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.tasks.core import tasks_complete
        from google_kit.services.tasks.models import TasksCompleteInput

        expected_body = _load("complete_expected_body.json")
        raw_task = {
            "id": "task001",
            "kind": "tasks#task",
            "title": "Buy milk",
            "status": "needsAction",
        }
        svc = MockGoogleService(responses={
            ("tasks", "get"): raw_task,
            ("tasks", "update"): {**raw_task, "status": "completed"},
        })
        tasks_complete(TasksCompleteInput(task_id="task001"), service=svc)

        update_reqs = svc.requests_for("tasks", "update")
        assert update_reqs, "No update request recorded"
        actual_body = update_reqs[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_get_then_put_two_calls(self) -> None:
        from google_kit.services.tasks.core import tasks_complete
        from google_kit.services.tasks.models import TasksCompleteInput

        task = _raw_task_stub()
        svc = MockGoogleService(responses={
            ("tasks", "get"): task,
            ("tasks", "update"): {**task, "status": "completed"},
        })
        tasks_complete(TasksCompleteInput(task_id="task001"), service=svc)
        assert len(svc.requests_for("tasks", "get")) == 1
        assert len(svc.requests_for("tasks", "update")) == 1


class TestTasksUpdate:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.tasks.core import tasks_update
        from google_kit.services.tasks.models import TasksUpdateInput

        expected_body = _load("update_expected_body.json")
        raw_task = {
            "id": "task001",
            "kind": "tasks#task",
            "title": "Buy milk",
            "status": "needsAction",
        }
        canned_updated = {
            "id": "task001",
            "kind": "tasks#task",
            "title": "Buy oat milk",
            "status": "needsAction",
            "due": "2025-02-01T00:00:00.000Z",
        }
        svc = MockGoogleService(responses={
            ("tasks", "get"): raw_task,
            ("tasks", "update"): canned_updated,
        })
        tasks_update(
            TasksUpdateInput(
                task_id="task001",
                title="Buy oat milk",
                due="2025-02-01",
            ),
            service=svc,
        )
        update_reqs = svc.requests_for("tasks", "update")
        assert update_reqs
        actual_body = update_reqs[0].body
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_partial_update_only_touches_provided_fields(self) -> None:
        from google_kit.services.tasks.core import tasks_update
        from google_kit.services.tasks.models import TasksUpdateInput

        raw_task = {"id": "t1", "kind": "tasks#task", "title": "Original", "status": "needsAction", "notes": "keep me"}
        svc = MockGoogleService(responses={
            ("tasks", "get"): raw_task,
            ("tasks", "update"): raw_task,
        })
        tasks_update(TasksUpdateInput(task_id="t1", title="Updated"), service=svc)
        body = svc.requests_for("tasks", "update")[0].body
        assert body["title"] == "Updated"
        assert body["notes"] == "keep me"


class TestTasksDelete:
    def test_mutation_request_recorded(self) -> None:
        from google_kit.services.tasks.core import tasks_delete
        from google_kit.services.tasks.models import TasksDeleteInput

        svc = MockGoogleService(responses={("tasks", "delete"): None})
        result = tasks_delete(TasksDeleteInput(task_id="task001"), service=svc)
        assert result.data.deleted is True
        assert result.data.task_id == "task001"

        delete_reqs = svc.requests_for("tasks", "delete")
        assert len(delete_reqs) == 1
        assert delete_reqs[0].kwargs.get("task") == "task001"

    def test_custom_tasklist(self) -> None:
        from google_kit.services.tasks.core import tasks_delete
        from google_kit.services.tasks.models import TasksDeleteInput

        svc = MockGoogleService(responses={("tasks", "delete"): None})
        tasks_delete(TasksDeleteInput(task_id="t1", tasklist="list123"), service=svc)
        req = svc.requests_for("tasks", "delete")[0]
        assert req.kwargs["tasklist"] == "list123"


class TestDueCoercion:
    def test_date_string(self) -> None:
        from google_kit.services.tasks.core import _coerce_due

        assert _coerce_due("2025-01-15") == "2025-01-15T00:00:00.000Z"

    def test_iso_datetime_utc(self) -> None:
        from google_kit.services.tasks.core import _coerce_due

        result = _coerce_due("2025-01-15T14:30:00+00:00")
        assert result == "2025-01-15T14:30:00.000Z"

    def test_iso_datetime_with_tz(self) -> None:
        from google_kit.services.tasks.core import _coerce_due

        result = _coerce_due("2025-01-15T10:00:00-05:00")
        assert result == "2025-01-15T15:00:00.000Z"


class TestRegistryIntegration:
    def test_all_six_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {
            "tasks.list_lists",
            "tasks.list",
            "tasks.create",
            "tasks.complete",
            "tasks.update",
            "tasks.delete",
        }
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_tasks_postures(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["tasks.list_lists"].posture == "read"
        assert specs["tasks.list"].posture == "read"
        assert specs["tasks.create"].posture == "write"
        assert specs["tasks.complete"].posture == "write"
        assert specs["tasks.update"].posture == "write"
        assert specs["tasks.delete"].posture == "destructive"
