"""Targeted fake-Google E2E coverage for high-risk read/write services.

This complements the generic 95-op matrix with registry-derived read/write
gating checks and multi-step request-shape assertions for Sheets, Docs, Slides,
Drive, Gmail, and Calendar. It never builds a real Google client.
"""
from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

import google_kit  # noqa: F401 - triggers registration
from google_kit.cli import main as cli_main
from google_kit.registry import all_specs
from kp_mcp_testkit.fixtures import compare_normalized

_E2E_HELPERS_PATH = Path(__file__).with_name("test_e2e_coverage.py")
_E2E_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "google_kit_test_e2e_coverage_helpers",
    _E2E_HELPERS_PATH,
)
assert _E2E_HELPERS_SPEC is not None and _E2E_HELPERS_SPEC.loader is not None
_E2E_HELPERS = importlib.util.module_from_spec(_E2E_HELPERS_SPEC)
sys.modules[_E2E_HELPERS_SPEC.name] = _E2E_HELPERS
_E2E_HELPERS_SPEC.loader.exec_module(_E2E_HELPERS)

SAMPLE_INPUTS = _E2E_HELPERS.SAMPLE_INPUTS
_FakeFactory = _E2E_HELPERS._FakeFactory
_assert_expected_vs_actual_envelope = _E2E_HELPERS._assert_expected_vs_actual_envelope
_argv_for = _E2E_HELPERS._argv_for
_expects_fake_call = _E2E_HELPERS._expects_fake_call
_seed_style_profile_for_sample = _E2E_HELPERS._seed_style_profile_for_sample


TARGET_SERVICES = ("sheets", "docs", "slides", "drive", "gmail", "calendar")
EXPECTED_SERVICE_COUNTS = {
    "sheets": 10,
    "docs": 12,
    "slides": 6,
    "drive": 12,
    "gmail": 15,
    "calendar": 6,
}
WRITE_POSTURES = {"write", "destructive"}
UMBRELLA_FLAG = "GOOGLE_KIT_ENABLE_WRITES"

KNOWN_TARGET_FLAGS = {
    UMBRELLA_FLAG,
    "GOOGLE_KIT_ENABLE_CALENDAR_WRITE",
    "GOOGLE_KIT_ENABLE_DOCS_WRITE",
    "GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE",
    "GOOGLE_KIT_ENABLE_DRIVE_WATCH",
    "GOOGLE_KIT_ENABLE_DRIVE_WRITE",
    "GOOGLE_KIT_ENABLE_GMAIL_WRITE",
    "GOOGLE_KIT_ENABLE_SHEETS_WRITE",
    "GOOGLE_KIT_ENABLE_SLIDES_WRITE",
}


def _target_specs() -> list[Any]:
    return sorted(
        [spec for spec in all_specs() if spec.name.split(".", 1)[0] in TARGET_SERVICES],
        key=lambda spec: spec.name,
    )


def _read_specs() -> list[Any]:
    return [spec for spec in _target_specs() if spec.posture == "read"]


def _mutating_specs() -> list[Any]:
    return [spec for spec in _target_specs() if spec.posture in WRITE_POSTURES]


def _umbrella_specs() -> list[Any]:
    return [spec for spec in _mutating_specs() if (spec.flag or "").endswith("_WRITE")]


def _spec_by_name(name: str) -> Any:
    return next(spec for spec in _target_specs() if spec.name == name)


def _clear_write_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in KNOWN_TARGET_FLAGS:
        monkeypatch.delenv(flag, raising=False)


def _enable_required_success_flags(spec: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    if spec.flag:
        monkeypatch.setenv(spec.flag, "1")
    if spec.name == "drive.upload" and SAMPLE_INPUTS[spec.name].get("share") == "anyone_reader":
        monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")


def _cli_json(op_name: str, factory: _FakeFactory, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    _seed_style_profile_for_sample(op_name)
    cli_main(_argv_for(op_name, SAMPLE_INPUTS[op_name]), _service_factory=factory)
    return json.loads(capsys.readouterr().out)


def _call_signature(factory: _FakeFactory) -> list[tuple[str, str, str]]:
    return [(call.service, call.resource, call.method) for call in factory.calls]


def _assert_expected_actual(expected: dict[str, Any], actual: dict[str, Any], label: str) -> None:
    match, diff = compare_normalized(expected, actual)
    assert match, f"{label}: EXPECTED vs ACTUAL mismatch\n{diff}"


def test_requested_service_registry_counts_and_op_names() -> None:
    actual_counts = {
        service: sum(1 for spec in all_specs() if spec.name.startswith(f"{service}."))
        for service in TARGET_SERVICES
    }
    _assert_expected_actual(EXPECTED_SERVICE_COUNTS, actual_counts, "target service op counts")
    assert sum(actual_counts.values()) == 61
    assert {spec.name for spec in _target_specs()} <= set(SAMPLE_INPUTS)


@pytest.mark.parametrize("spec", _read_specs(), ids=lambda spec: spec.name)
def test_read_ops_succeed_without_write_flags(
    spec: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_write_flags(monkeypatch)
    factory = _FakeFactory()

    actual = _cli_json(spec.name, factory, capsys)

    _assert_expected_vs_actual_envelope(spec, actual)
    if _expects_fake_call(spec.name):
        assert factory.calls, f"{spec.name}: expected fake API usage without write flags"
    assert spec.flag is None


@pytest.mark.parametrize("spec", _mutating_specs(), ids=lambda spec: spec.name)
def test_mutating_ops_are_blocked_without_explicit_flags(
    spec: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_write_flags(monkeypatch)
    factory = _FakeFactory()

    with pytest.raises(SystemExit) as exc:
        cli_main(_argv_for(spec.name, SAMPLE_INPUTS[spec.name]), _service_factory=factory)

    assert exc.value.code != 0
    assert not factory.calls
    assert spec.flag in capsys.readouterr().err


@pytest.mark.parametrize("spec", _mutating_specs(), ids=lambda spec: spec.name)
def test_mutating_ops_succeed_with_exact_required_flag(
    spec: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_write_flags(monkeypatch)
    _enable_required_success_flags(spec, monkeypatch)
    factory = _FakeFactory()

    actual = _cli_json(spec.name, factory, capsys)

    _assert_expected_vs_actual_envelope(spec, actual)
    if _expects_fake_call(spec.name):
        assert factory.calls, f"{spec.name}: expected fake API usage with {spec.flag}=1"


@pytest.mark.parametrize("spec", _umbrella_specs(), ids=lambda spec: spec.name)
def test_standard_write_ops_succeed_with_umbrella_flag(
    spec: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_write_flags(monkeypatch)
    monkeypatch.setenv(UMBRELLA_FLAG, "1")
    if spec.name == "drive.upload" and SAMPLE_INPUTS[spec.name].get("share") == "anyone_reader":
        monkeypatch.setenv("GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE", "1")
    factory = _FakeFactory()

    actual = _cli_json(spec.name, factory, capsys)

    _assert_expected_vs_actual_envelope(spec, actual)
    if _expects_fake_call(spec.name):
        assert factory.calls, f"{spec.name}: expected fake API usage with umbrella write flag"


RICH_FLOW_SCENARIOS: list[dict[str, Any]] = [
    {
        "op": "sheets.create",
        "expected_data": {
            "spreadsheet_id": "sheet-1",
            "url": "https://docs.google.com/spreadsheets/d/sheet-1",
            "title": "E2E Sheet",
            "sheets": ["Data"],
        },
        "expected_calls": [
            ("sheets", "spreadsheets", "create"),
            ("drive", "files", "update"),
        ],
    },
    {
        "op": "sheets.write",
        "expected_data": {
            "updated_rows": 1,
            "updated_columns": 2,
            "updated_range": "Sheet1!A1",
        },
        "expected_calls": [
            ("sheets", "spreadsheets.values", "clear"),
            ("sheets", "spreadsheets.values", "update"),
        ],
    },
    {
        "op": "docs.from_markdown",
        "expected_data": {
            "doc_id": "file-1",
            "url": "https://drive/file-1",
            "title": "E2E Doc",
            "formatting_requests_applied": 2,
        },
        "expected_calls": [
            ("drive", "files", "create"),
            ("docs", "documents", "get"),
            ("docs", "documents", "batchUpdate"),
        ],
    },
    {
        "op": "slides.add_slide",
        "expected_data": {
            "presentation_id": "pres-1",
            "slide_id": "slide-1",
        },
        "expected_calls": [
            ("slides", "presentations", "batchUpdate"),
            ("slides", "presentations", "get"),
            ("slides", "presentations", "batchUpdate"),
            ("slides", "presentations", "get"),
            ("slides", "presentations", "batchUpdate"),
        ],
    },
    {
        "op": "drive.fetch",
        "expected_data": {
            "id": "file-1",
            "title": "E2E File",
            "mime_type": "application/vnd.google-apps.document",
            "platform": "google_docs",
            "content": "E2E\n\nDrive content",
            "fetch_method": "drive_export_html_stripped",
            "web_url": "https://drive/file-1",
        },
        "expected_calls": [
            ("drive", "files", "get"),
            ("drive", "files", "export"),
        ],
    },
    {
        "op": "drive.upload",
        "expected_data": {
            "id": "file-1",
            "url": "https://drive/file-1",
            "name": "hello.txt",
            "mime_type": "text/plain",
            "shared": True,
        },
        "expected_calls": [
            ("drive", "files", "create"),
            ("drive", "permissions", "create"),
        ],
    },
    {
        "op": "gmail.thread_get",
        "expected_data": {
            "id": "thread-1",
            "history_id": "10",
            "snippet": "snippet",
            "message_count": 1,
            "messages": [{
                "id": "msg-1",
                "thread_id": "thread-1",
                "snippet": "Hello",
                "subject": "E2E",
                "from_": "sender@example.com",
                "date": "Fri, 19 Jun 2026 09:00:00 +0000",
                "body": "Hello",
                "label_ids": ["INBOX"],
            }],
        },
        "expected_calls": [
            ("gmail", "users.threads", "get"),
        ],
    },
    {
        "op": "gmail.batch_modify",
        "expected_data": {
            "modified_count": 2,
            "ids": ["msg-1", "msg-2"],
            "add_label_ids": ["STARRED"],
            "remove_label_ids": [],
        },
        "expected_calls": [
            ("gmail", "users.messages", "batchModify"),
        ],
    },
    {
        "op": "calendar.update",
        "expected_data": {
            "id": "event-1",
            "summary": "Updated E2E event",
            "html_link": "https://calendar/event-1",
        },
        "expected_calls": [
            ("calendar", "events", "get"),
            ("calendar", "events", "patch"),
        ],
    },
    {
        "op": "calendar.watch",
        "expected_data": {
            "id": "calendar-channel",
            "resource_id": "resource-1",
            "resource_uri": "https://calendar/resource",
            "expiration": "1893456000000",
        },
        "expected_calls": [
            ("calendar", "events", "watch"),
        ],
    },
]


@pytest.mark.parametrize(
    "scenario",
    RICH_FLOW_SCENARIOS,
    ids=[case["op"] for case in RICH_FLOW_SCENARIOS],
)
def test_rich_service_flows_expected_vs_actual(
    scenario: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    op_name = scenario["op"]
    spec = _spec_by_name(op_name)
    _clear_write_flags(monkeypatch)
    if spec.posture in WRITE_POSTURES:
        _enable_required_success_flags(spec, monkeypatch)
    factory = _FakeFactory()

    actual = _cli_json(op_name, factory, capsys)

    _assert_expected_vs_actual_envelope(spec, actual)
    _assert_expected_actual(scenario["expected_data"], actual["data"], f"{op_name} data")
    assert _call_signature(factory) == scenario["expected_calls"]

    if op_name == "sheets.write":
        update = factory.calls[1]
        _assert_expected_actual(
            {
                "spreadsheetId": "sheet-1",
                "range": "Sheet1!A1",
                "valueInputOption": "USER_ENTERED",
                "body": {"values": [["a", "b"]]},
            },
            update.kwargs,
            "sheets.write request",
        )
    elif op_name == "slides.add_slide":
        insert_texts = [
            call.kwargs["body"]["requests"][0]["insertText"]["text"]
            for call in factory.calls
            if call.method == "batchUpdate"
            and "insertText" in call.kwargs["body"]["requests"][0]
        ]
        assert insert_texts == ["Title", "Body"]
    elif op_name == "drive.upload":
        permission = factory.calls[1]
        _assert_expected_actual(
            {"fileId": "file-1", "body": {"type": "anyone", "role": "reader"}},
            permission.kwargs,
            "drive.upload public-share request",
        )
    elif op_name == "calendar.update":
        patch = factory.calls[1]
        expected_attendees = [
            {"email": "person@example.com", "displayName": "Person", "responseStatus": "accepted"},
            {"email": "new@example.com"},
        ]
        _assert_expected_actual(
            {
                "eventId": "event-1",
                "sendUpdates": "all",
                "body": {"summary": "Updated E2E event", "attendees": expected_attendees},
            },
            {
                "eventId": patch.kwargs["eventId"],
                "sendUpdates": patch.kwargs["sendUpdates"],
                "body": patch.kwargs["body"],
            },
            "calendar.update merged-attendee patch",
        )
