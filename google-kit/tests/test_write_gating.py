"""Global F5 write-gating coverage (operator decision: gate every mutation).

Asserts the registry-level invariant (every write/destructive op carries an
off-by-default flag), the umbrella/elevated-gate semantics of
:func:`google_kit.core.flags.is_flag_enabled`, and end-to-end CLI enforcement
on a per-service sample (blocked without the flag, allowed with the per-service
flag, allowed via the ``GOOGLE_KIT_ENABLE_WRITES`` umbrella).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

import google_kit  # noqa: F401 - triggers registration
from google_kit.cli import main as cli_main
from google_kit.core.flags import ENABLE_WRITES_FLAG, is_flag_enabled
from google_kit.registry import all_specs

_MUTATING = {"write", "destructive"}

#: Elevated, capability-specific gates that must NOT be satisfied by the umbrella.
_NON_UMBRELLA_FLAGS = {
    "GOOGLE_KIT_ENABLE_DRIVE_WATCH",
    "GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE",
}


class _Executable:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _Node:
    """Chainable fake: resource accessors recurse, terminal verbs return a response."""

    _RESOURCES = {"tasks", "tasklists", "users", "messages", "spreadsheets", "values"}

    def __init__(self, root: "_FakeService", path: list[str]) -> None:
        self._root = root
        self._path = path

    def __getattr__(self, name: str) -> Any:
        def _method(**kwargs: Any) -> Any:
            if name in self._RESOURCES:
                return _Node(self._root, [*self._path, name])
            self._root.calls.append((".".join(self._path), name))
            return _Executable(self._root.response_for(name, kwargs))

        return _method


class _FakeService(_Node):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        super().__init__(self, [])

    def response_for(self, method: str, kwargs: dict[str, Any]) -> Any:
        body = kwargs.get("body") or {}
        if method == "insert":  # tasks.create
            return {"id": "task-1", "title": body.get("title", "Task"), "status": "needsAction"}
        if method == "send":  # gmail.send
            return {"id": "sent-1", "threadId": "thread-1", "labelIds": ["SENT"]}
        return {}


class _Factory:
    def __init__(self) -> None:
        self.svc = _FakeService()

    def __call__(self, op_name: str, *, profile: str | None = None) -> _FakeService:
        del op_name, profile
        return self.svc

    @property
    def calls(self) -> list[tuple[str, str]]:
        return self.svc.calls


def test_every_mutating_op_is_flag_gated() -> None:
    ungated = [s.name for s in all_specs() if s.posture in _MUTATING and not s.flag]
    assert ungated == [], f"write/destructive ops missing an F5 flag: {ungated}"


def test_read_and_admin_ops_are_not_gated() -> None:
    # The gate is a mutation concern only; never gate read/admin posture ops.
    gated_reads = [
        s.name
        for s in all_specs()
        if s.posture not in _MUTATING and s.flag and s.flag.endswith("_WRITE")
    ]
    assert gated_reads == []


def test_umbrella_satisfies_only_write_suffixed_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENABLE_WRITES_FLAG, "1")
    for flag in {
        s.flag for s in all_specs() if s.posture in _MUTATING and s.flag
    }:
        if flag.endswith("_WRITE"):
            assert is_flag_enabled(flag), f"umbrella should satisfy {flag}"
        else:
            assert not is_flag_enabled(flag), f"umbrella must NOT satisfy elevated {flag}"


def test_elevated_gates_require_their_own_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENABLE_WRITES_FLAG, "1")
    for flag in _NON_UMBRELLA_FLAGS:
        monkeypatch.delenv(flag, raising=False)
        assert not is_flag_enabled(flag)
        monkeypatch.setenv(flag, "1")
        assert is_flag_enabled(flag)
        monkeypatch.delenv(flag, raising=False)


def test_ungated_flag_is_always_enabled() -> None:
    assert is_flag_enabled(None) is True
    assert is_flag_enabled("") is True


# ─── CLI enforcement on a per-service sample (tasks) ──────────────────────────

_TASKS_CREATE_ARGV = ["tasks", "create", "--title", "Task", "--notes", "Do it"]


def test_cli_blocks_tasks_create_without_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
    monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
    factory = _Factory()

    with pytest.raises(SystemExit) as exc:
        cli_main(_TASKS_CREATE_ARGV, _service_factory=factory)

    assert exc.value.code != 0
    assert not factory.calls, "no Google API call should fire when the gate blocks"
    assert "GOOGLE_KIT_ENABLE_TASKS_WRITE" in capsys.readouterr().err


def test_cli_allows_tasks_create_with_per_service_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", "1")
    monkeypatch.delenv(ENABLE_WRITES_FLAG, raising=False)
    factory = _Factory()

    cli_main(_TASKS_CREATE_ARGV, _service_factory=factory)
    out = json.loads(capsys.readouterr().out)

    assert out["data"]["id"] == "task-1"
    assert any(method == "insert" for _, method in factory.calls)


def test_cli_allows_tasks_create_with_umbrella(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GOOGLE_KIT_ENABLE_TASKS_WRITE", raising=False)
    monkeypatch.setenv(ENABLE_WRITES_FLAG, "1")
    factory = _Factory()

    cli_main(_TASKS_CREATE_ARGV, _service_factory=factory)
    out = json.loads(capsys.readouterr().out)

    assert out["data"]["id"] == "task-1"
    assert any(method == "insert" for _, method in factory.calls)
