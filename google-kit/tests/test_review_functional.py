"""Review-round functional checks for non-Drive CLI/MCP dispatch."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest


_METHODS = {
    "batchUpdate",
    "create",
    "delete",
    "get",
    "getProfile",
    "insert",
    "list",
    "patch",
    "query",
    "send",
    "setPublishSettings",
    "update",
}


class _Exec:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _Resource:
    def __init__(self, svc: "_GoogleFake", path: list[str]) -> None:
        self._svc = svc
        self._path = path

    def __getattr__(self, name: str) -> Any:
        if name in _METHODS:
            def _method(**kwargs: Any) -> _Exec:
                resource = self._path[-1]
                self._svc.requests.append((resource, name, kwargs))
                return _Exec(self._svc.responses.get((resource, name)))

            return _method

        def _resource(*args: Any, **kwargs: Any) -> "_Resource":
            return _Resource(self._svc, [*self._path, name])

        return _resource


class _GoogleFake:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def _resource(*args: Any, **kwargs: Any) -> _Resource:
            return _Resource(self, [name])

        return _resource


def _mcp_call(tool_name: str, arguments: dict[str, Any], svc: _GoogleFake) -> dict[str, Any]:
    from mcp.types import CallToolRequest, CallToolRequestParams

    from google_kit.mcp import build_mcp_server

    server = build_mcp_server(_service_factory=lambda op_name: svc)
    handler = server.request_handlers[CallToolRequest]

    async def _run() -> Any:
        return await handler(
            CallToolRequest(
                method="tools/call",
                params=CallToolRequestParams(name=tool_name, arguments=arguments),
            )
        )

    result = asyncio.run(_run())
    root = getattr(result, "root", result)
    return json.loads(root.content[0].text)


def test_mcp_dispatch_representative_non_drive_ops_return_envelope() -> None:
    cases = [
        (
            "tasks_list_lists",
            {"max_results": 5},
            _GoogleFake({("tasklists", "list"): {"items": [{"id": "tl1", "title": "Work"}]}}),
            "tasks.list_lists",
        ),
        (
            "gmail_list",
            {"max_results": 1},
            _GoogleFake({("messages", "list"): {"messages": [{"id": "m1", "threadId": "t1"}]}}),
            "gmail.list",
        ),
        (
            "forms_list_responses",
            {"form_id": "form1", "page_size": 1},
            _GoogleFake({
                ("responses", "list"): {
                    "responses": [{"responseId": "r1", "answers": {}}],
                    "nextPageToken": "next",
                }
            }),
            "forms.list_responses",
        ),
    ]

    for tool_name, args, svc, op_name in cases:
        payload = _mcp_call(tool_name, args, svc)
        assert set(payload) == {"data", "meta", "page", "warnings"}
        assert payload["meta"]["op"] == op_name
        assert payload["warnings"] == []


def test_mcp_dispatch_maps_core_errors_to_structured_payload() -> None:
    from google_kit.core.errors import NotFound

    svc = _GoogleFake({("tasklists", "list"): NotFound("missing task list", op="tasks.list_lists")})
    payload = _mcp_call("tasks_list_lists", {}, svc)

    assert payload == {
        "error": "NotFound",
        "message": "missing task list",
        "op": "tasks.list_lists",
    }


def test_cli_uses_taxonomy_exit_code_for_google_kit_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from google_kit.cli import main
    from google_kit.core.errors import NotFound

    def _factory(op_name: str, *, profile: str | None = None) -> Any:
        raise NotFound("not found", op=op_name)

    with pytest.raises(SystemExit) as exc:
        main(["tasks", "list-lists"], _service_factory=_factory)

    assert exc.value.code == 6
    assert "not found" in capsys.readouterr().err


def test_cli_bootstrap_dry_run_is_json_and_writes_nothing(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import google_kit.bootstrap as gk_bootstrap
    from google_kit.cli import main

    paths = {
        "cursor": tmp_path / "mcp.json",
        "codex": tmp_path / "config.toml",
        "claude": tmp_path / ".claude.json",
    }
    monkeypatch.setattr(gk_bootstrap, "default_platform_paths", lambda: paths)

    with pytest.raises(SystemExit) as exc:
        main(["bootstrap", "--dry-run"])

    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().err)
    assert out["status"] == "refused"
    assert out["reason_codes"] == ["context_required"]
    assert not any(path.exists() for path in paths.values())


def test_build_service_for_op_maps_prefixes_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import google_kit.core.client as client_mod
    from google_kit.core.auth import build_service_for_op
    import kp_mcp_bootstrap.config as config_mod
    import kp_mcp_bootstrap.secrets as secrets_mod

    captured: list[tuple[str, str, str]] = []

    class _Store:
        def __init__(self, *, profile: str) -> None:
            self.profile = profile

        def get(self, key: str) -> str:
            return "client-id" if key == "client_id" else key

    def _build(api_name: str, api_version: str, store: _Store, *, client_id: str) -> object:
        captured.append((api_name, api_version, client_id))
        return object()

    monkeypatch.setattr(config_mod, "load_config", lambda: SimpleNamespace(profile="default"))
    monkeypatch.setattr(secrets_mod, "KeychainSecretStore", _Store)
    monkeypatch.setattr(client_mod, "build_authorized_service", _build)

    cases = {
        "calendar.list": ("calendar", "v3"),
        "docs.batch_update": ("docs", "v1"),
        "events.list": ("workspaceevents", "v1"),
        "people.get": ("people", "v1"),
        "script.run": ("script", "v1"),
    }

    for op_name in cases:
        build_service_for_op(op_name)

    assert captured == [(api, version, "client-id") for api, version in cases.values()]


def test_sparse_task_and_calendar_list_items_do_not_crash() -> None:
    from google_kit.services.calendar.core import calendar_list
    from google_kit.services.calendar.models import CalendarListInput
    from google_kit.services.tasks.core import tasks_list, tasks_list_lists
    from google_kit.services.tasks.models import TasksListInput, TasksListListsInput

    task_lists = tasks_list_lists(
        TasksListListsInput(),
        service=_GoogleFake({("tasklists", "list"): {"items": [{"title": "Untitled"}]}}),
    )
    tasks = tasks_list(
        TasksListInput(),
        service=_GoogleFake({("tasks", "list"): {"items": [{"title": "Untitled"}]}}),
    )
    events = calendar_list(
        CalendarListInput(days=1),
        service=_GoogleFake({("events", "list"): {"items": [{"summary": "Untitled"}]}}),
    )

    assert task_lists.data.task_lists[0].id == ""
    assert tasks.data.tasks[0].id == ""
    assert events.data.events[0].id == ""
