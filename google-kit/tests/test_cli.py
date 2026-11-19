"""Tests for google-kit CLI adapter.

Parity: generic-CLI DONE; sandbox-e2e DEFERRED(P6)
"""
from __future__ import annotations

import json
from typing import Any

import pytest

import google_kit  # noqa: F401 — triggers registration
from google_kit.cli import _build_parser, _coerce_argv_to_model, main
from google_kit.registry import all_specs, get
from kp_mcp_testkit.mock_google import MockGoogleService


def _make_factory(mock_svc: Any):
    """Return a service factory that always returns mock_svc."""
    def factory(op_name: str, *, profile: str | None = None) -> Any:
        return mock_svc
    return factory


class TestParserStructure:
    def test_help_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_no_args_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "google-kit" in captured.out or "google-kit" in captured.err

    def test_all_ops_parseable(self) -> None:
        parser = _build_parser()
        assert parser is not None
        specs = list(all_specs())
        # >= cutover-minimum baseline (41); grows with E1/E2 expansion.
        assert len(specs) >= 41

    def test_service_without_op_exits_nonzero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["tasks"])
        assert exc.value.code != 0

    def test_op_help_exits_zero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["tasks", "list-lists", "--help"])
        assert exc.value.code == 0

    def test_all_services_present(self) -> None:
        parser = _build_parser()
        services = {s.name.split(".")[0] for s in all_specs()}
        for svc in services:
            with pytest.raises(SystemExit) as exc:
                main([svc, "--help"])
            assert exc.value.code == 0

    def test_hyphenated_ops_registered(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit) as exc:
            main(["tasks", "list-lists", "--help"])
        assert exc.value.code == 0


class TestArgCoercion:
    def test_integer_field_coerced(self) -> None:
        spec = get("tasks.list_lists")
        import argparse
        ns = argparse.Namespace(max_results=50)
        inp = _coerce_argv_to_model(spec, ns)
        assert inp.max_results == 50

    def test_default_used_when_field_absent(self) -> None:
        spec = get("tasks.list_lists")
        import argparse
        ns = argparse.Namespace()
        inp = _coerce_argv_to_model(spec, ns)
        assert inp.max_results == 100

    def test_string_field_passthrough(self) -> None:
        spec = get("tasks.list")
        import argparse
        ns = argparse.Namespace(tasklist="@default", max_results=None, show_completed=None)
        inp = _coerce_argv_to_model(spec, ns)
        assert inp.tasklist == "@default"

    def test_json_array_field_parsed(self) -> None:
        import argparse

        from google_kit.cli import _coerce_argv_to_model

        spec = get("tasks.list_lists")
        ns = argparse.Namespace(max_results=None)
        inp = _coerce_argv_to_model(spec, ns)
        assert inp.max_results == 100

    def test_boolean_string_coercion(self) -> None:
        import argparse

        spec = get("tasks.list")
        ns = argparse.Namespace(
            tasklist="@default",
            max_results=None,
            show_completed="true",
        )
        inp = _coerce_argv_to_model(spec, ns)
        assert inp.show_completed is True


class TestMockInvocation:
    """Mock invocations that never touch real Google credentials."""

    def _tasks_mock_factory(self) -> Any:
        svc = MockGoogleService(responses={
            ("tasklists", "list"): {
                "items": [{"id": "abc", "title": "My Tasks", "kind": "tasks#taskList"}]
            }
        })
        return _make_factory(svc)

    def test_tasks_list_lists_json_output(self, capsys: pytest.CaptureFixture) -> None:
        main(["tasks", "list-lists"], _service_factory=self._tasks_mock_factory())
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "data" in data
        assert data["data"]["count"] == 1

    def test_tasks_list_lists_text_output(self, capsys: pytest.CaptureFixture) -> None:
        main(["--format", "text", "tasks", "list-lists"], _service_factory=self._tasks_mock_factory())
        captured = capsys.readouterr()
        assert "task_lists" in captured.out or "count" in captured.out

    def test_run_id_in_meta(self, capsys: pytest.CaptureFixture) -> None:
        main(["tasks", "list-lists"], _service_factory=self._tasks_mock_factory())
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "meta" in data

    def test_profile_flag_passed_to_factory(self) -> None:
        received: list[str] = []

        def factory(op_name: str, *, profile: str | None = None) -> Any:
            received.append(profile or "")
            svc = MockGoogleService(responses={
                ("tasklists", "list"): {"items": []}
            })
            return svc

        main(["--profile", "work", "tasks", "list-lists"], _service_factory=factory)
        assert received and received[0] == "work"


class TestErrorHandling:
    def test_auth_failure_exits_nonzero(self, capsys: pytest.CaptureFixture) -> None:
        def failing_factory(op_name: str, *, profile: str | None = None) -> Any:
            raise RuntimeError("Keychain unavailable in test")

        with pytest.raises(SystemExit) as exc:
            main(["tasks", "list-lists"], _service_factory=failing_factory)
        assert exc.value.code != 0

    def test_unknown_op_exits_nonzero(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["tasks", "nonexistent-op"])
        assert exc.value.code != 0
