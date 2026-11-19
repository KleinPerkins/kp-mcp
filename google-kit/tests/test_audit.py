"""Tests for google_kit.core.audit."""
from pathlib import Path

import pytest

from google_kit.core.audit import read_audit, write_audit
from google_kit.core.run_id import set_run_id, reset_run_id


def test_write_and_read_basic(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    write_audit(
        actor="default",
        op="drive.create",
        normalized_request={"name": "doc.txt"},
        target_ids=["file-id-1"],
        result="ok",
        audit_file=audit_file,
    )
    records = read_audit(audit_file=audit_file)
    assert len(records) == 1
    r = records[0]
    assert r["actor"] == "default"
    assert r["op"] == "drive.create"
    assert r["target_ids"] == ["file-id-1"]
    assert r["result"] == "ok"
    assert r["deviation_flag"] is False
    assert "ts" in r


def test_multiple_records_appended(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    for i in range(3):
        write_audit(
            actor="user",
            op=f"drive.op{i}",
            normalized_request={},
            target_ids=[],
            result="ok",
            audit_file=audit_file,
        )
    records = read_audit(audit_file=audit_file)
    assert len(records) == 3


def test_pii_redacted_in_normalized_request(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    write_audit(
        actor="default",
        op="gmail.send",
        normalized_request={"to": "alice@example.com", "subject": "secret"},
        target_ids=[],
        result="ok",
        audit_file=audit_file,
    )
    records = read_audit(audit_file=audit_file)
    req = records[0]["normalized_request"]
    assert "alice@example.com" not in str(req)
    assert req["to"] == "[REDACTED]"
    assert req["subject"] == "[REDACTED]"


def test_run_id_included(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    token = set_run_id("testrunid1234567")
    try:
        write_audit(
            actor="default",
            op="drive.create",
            normalized_request={},
            target_ids=[],
            result="ok",
            audit_file=audit_file,
        )
    finally:
        reset_run_id(token)
    records = read_audit(audit_file=audit_file)
    assert records[0]["run_id"] == "testrunid1234567"


def test_filter_by_op(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    for op in ["drive.create", "drive.delete", "gmail.send"]:
        write_audit(
            actor="u",
            op=op,
            normalized_request={},
            target_ids=[],
            result="ok",
            audit_file=audit_file,
        )
    drive_records = read_audit(op="drive", audit_file=audit_file)
    assert len(drive_records) == 2
    assert all(r["op"].startswith("drive") for r in drive_records)


def test_filter_by_actor(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    for actor in ["alice", "bob", "alice"]:
        write_audit(
            actor=actor,
            op="drive.fetch",
            normalized_request={},
            target_ids=[],
            result="ok",
            audit_file=audit_file,
        )
    alice_records = read_audit(actor="alice", audit_file=audit_file)
    assert len(alice_records) == 2


def test_filter_by_since(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    write_audit(
        actor="u",
        op="drive.fetch",
        normalized_request={},
        target_ids=[],
        result="ok",
        audit_file=audit_file,
    )
    records = read_audit(audit_file=audit_file)
    ts_first = records[0]["ts"]
    write_audit(
        actor="u",
        op="drive.create",
        normalized_request={},
        target_ids=[],
        result="ok",
        audit_file=audit_file,
    )
    later_records = read_audit(since=ts_first, audit_file=audit_file)
    assert any(r["op"] == "drive.fetch" for r in later_records)


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    assert read_audit(audit_file=audit_file) == []


def test_deviation_flag_stored(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    write_audit(
        actor="u",
        op="drive.create",
        normalized_request={},
        target_ids=[],
        result="ok",
        deviation_flag=True,
        audit_file=audit_file,
    )
    records = read_audit(audit_file=audit_file)
    assert records[0]["deviation_flag"] is True


def test_directory_created_if_missing(tmp_path: Path) -> None:
    audit_file = tmp_path / "deep" / "nested" / "audit.jsonl"
    write_audit(
        actor="u",
        op="x",
        normalized_request={},
        target_ids=[],
        result="ok",
        audit_file=audit_file,
    )
    assert audit_file.exists()
