"""Richer audit trail (#3): audit.jsonl records WHAT was mutated, redacted.

Proves that :func:`google_kit.core.client.execute_api_call` threads the validated
input (``normalized_request``) and mutated resource ids (``target_ids``) into the
append-only audit log, with PII/credentials redacted via ``redact_dict``, and that
read-posture calls never write an audit record.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import google_kit  # noqa: F401 - triggers registration
from google_kit.core.audit import read_audit
from google_kit.core.client import _extract_target_ids, execute_api_call
from google_kit.core.errors import Permission, Transient


def _audit_file(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


def test_write_records_redacted_request_and_target_ids(tmp_path: Path) -> None:
    audit_file = _audit_file(tmp_path)

    result = execute_api_call(
        lambda: {"id": "file-1", "name": "ignored-display-name"},
        op="drive.create",
        posture="write",
        actor="tester",
        normalized_request={
            "title": "Q3 secret plan",
            "share_with": "person@example.com",
            "raw_note": "token=supersecretvalue123",
        },
        audit_file=audit_file,
    )
    assert result["id"] == "file-1"

    records = read_audit(op="drive.create", audit_file=audit_file)
    assert len(records) == 1
    rec = records[0]

    assert rec["op"] == "drive.create"
    assert rec["actor"] == "tester"
    assert rec["result"] == "ok"
    # target id auto-extracted from the result's id field
    assert rec["target_ids"] == ["file-1"]

    nr = rec["normalized_request"]
    # PII field name redacted wholesale; email + inline credential scrubbed from values.
    assert nr["title"] == "[REDACTED]"
    assert "person@example.com" not in nr["share_with"]
    assert "supersecretvalue123" not in str(nr)


def test_explicit_target_ids_override_extraction(tmp_path: Path) -> None:
    audit_file = _audit_file(tmp_path)

    execute_api_call(
        lambda: None,  # delete returns no body
        op="drive.permissions",
        posture="destructive",
        normalized_request={"file_id": "file-9", "permission_id": "perm-1"},
        target_ids=["file-9"],
        audit_file=audit_file,
    )

    rec = read_audit(op="drive.permissions", audit_file=audit_file)[0]
    assert rec["target_ids"] == ["file-9"]


def test_failed_mutation_writes_error_audit_record(tmp_path: Path) -> None:
    """A mutation whose API call fails must emit an audit record (#3)."""
    audit_file = _audit_file(tmp_path)

    def _boom() -> None:
        raise Permission("caller lacks drive.file scope", op="drive.create")

    with pytest.raises(Permission):
        execute_api_call(
            _boom,
            op="drive.create",
            posture="write",
            actor="tester",
            normalized_request={"title": "Q3 secret plan"},
            audit_file=audit_file,
        )

    rec = read_audit(op="drive.create", audit_file=audit_file)[0]
    assert rec["result"] == "error"
    assert rec["actor"] == "tester"
    # Failure summary names the error class; PII field still redacted.
    assert rec["error"].startswith("Permission:")
    assert rec["normalized_request"]["title"] == "[REDACTED]"
    # No result available on failure → no auto-extracted target ids.
    assert rec["target_ids"] == []


def test_failed_mutation_uses_explicit_target_ids(tmp_path: Path) -> None:
    """On failure, explicit list target_ids are still recorded (known from input)."""
    audit_file = _audit_file(tmp_path)

    def _boom() -> None:
        raise Transient("503 server error", op="drive.permissions")

    with pytest.raises(Transient):
        execute_api_call(
            _boom,
            op="drive.permissions",
            posture="destructive",
            normalized_request={"file_id": "file-9"},
            target_ids=["file-9"],
            max_attempts=1,
            audit_file=audit_file,
        )

    rec = read_audit(op="drive.permissions", audit_file=audit_file)[0]
    assert rec["result"] == "error"
    assert rec["target_ids"] == ["file-9"]


def test_failed_mutation_error_summary_redacts_secrets(tmp_path: Path) -> None:
    """The recorded error summary must not leak emails/credentials."""
    audit_file = _audit_file(tmp_path)

    def _boom() -> None:
        raise Permission(
            "denied for user person@example.com token=supersecretvalue123",
            op="drive.create",
        )

    with pytest.raises(Permission):
        execute_api_call(
            _boom,
            op="drive.create",
            posture="write",
            normalized_request={},
            audit_file=audit_file,
        )

    rec = read_audit(op="drive.create", audit_file=audit_file)[0]
    assert "person@example.com" not in rec["error"]
    assert "supersecretvalue123" not in rec["error"]


def test_failed_read_writes_no_audit_record(tmp_path: Path) -> None:
    """A failed read posture call must NOT write an audit record."""
    audit_file = _audit_file(tmp_path)

    def _boom() -> None:
        raise Permission("nope", op="drive.fetch")

    with pytest.raises(Permission):
        execute_api_call(
            _boom,
            op="drive.fetch",
            posture="read",
            audit_file=audit_file,
        )

    assert read_audit(audit_file=audit_file) == []


def test_successful_mutation_has_no_error_field(tmp_path: Path) -> None:
    """Successful records keep their stable shape (no `error` key)."""
    audit_file = _audit_file(tmp_path)

    execute_api_call(
        lambda: {"id": "ok-1"},
        op="tasks.create",
        posture="write",
        audit_file=audit_file,
    )

    rec = read_audit(op="tasks.create", audit_file=audit_file)[0]
    assert "error" not in rec


def test_read_posture_writes_no_audit_record(tmp_path: Path) -> None:
    audit_file = _audit_file(tmp_path)

    execute_api_call(
        lambda: {"id": "file-1"},
        op="drive.fetch",
        posture="read",
        normalized_request={"url_or_id": "file-1"},
        audit_file=audit_file,
    )

    assert not audit_file.exists()
    assert read_audit(audit_file=audit_file) == []


def test_missing_normalized_request_records_empty_dict(tmp_path: Path) -> None:
    audit_file = _audit_file(tmp_path)

    execute_api_call(
        lambda: {"id": "x-1"},
        op="tasks.create",
        posture="write",
        audit_file=audit_file,
    )

    rec = read_audit(op="tasks.create", audit_file=audit_file)[0]
    assert rec["normalized_request"] == {}
    assert rec["target_ids"] == ["x-1"]


@pytest.mark.parametrize(
    "result,expected",
    [
        ({"id": "a"}, ["a"]),
        ({"fileId": "f", "messageId": "m"}, ["f", "m"]),
        ({"spreadsheetId": "s", "kind": "sheet", "etag": "abc"}, ["s"]),
        ({"name": "notes/note-1"}, []),  # display/resource name is NOT an id key
        ({"id": "dup", "thingId": "dup"}, ["dup"]),  # de-duplicated, order-stable
        (None, []),
        ("not-a-dict", []),
        ({"id": ""}, []),  # empty string ignored
    ],
)
def test_extract_target_ids_heuristic(result: object, expected: list[str]) -> None:
    assert _extract_target_ids(result) == expected


def test_core_fn_threads_normalized_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # End-to-end through a real core fn: drive_create must pass its validated
    # input + the created file id into the audit log.
    from google_kit.services.drive.core import drive_create
    from google_kit.services.drive.models import DriveCreateInput

    captured: dict[str, object] = {}

    def _fake_write_audit(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("google_kit.core.client.write_audit", _fake_write_audit)

    class _Files:
        def create(self, **_: object) -> "_Files":
            return self

        def execute(self) -> dict[str, str]:
            return {"id": "file-123", "name": "Plan", "webViewLink": "https://drive/file-123"}

    class _Svc:
        def files(self) -> _Files:
            return _Files()

    drive_create(DriveCreateInput(title="My Plan", doc_type="doc"), service=_Svc())

    assert captured["op"] == "drive.create"
    assert captured["target_ids"] == ["file-123"]
    assert "title" in captured["normalized_request"]  # type: ignore[operator]
