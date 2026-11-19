"""QA #1 regression: keep.create must record the created note id in the audit log.

The Keep API returns a newly created note's identifier in its resource-path
``name`` field (``notes/<id>``), never a top-level ``*Id`` key. ``client._extract_target_ids``
deliberately excludes ``name`` (it is a display title for most APIs), so a
create whose id lives only in ``name`` must thread ``target_ids`` explicitly —
exactly as ``client.execute_api_call`` documents for Keep/Workspace Events.

Before the fix, ``keep.create`` relied on auto-extraction and silently wrote an
audit record with ``target_ids == []`` — the mutated resource was unidentifiable
in the audit trail.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import google_kit  # noqa: F401 - triggers registration
from google_kit.core.audit import read_audit
from google_kit.services.keep.core import keep_create
from google_kit.services.keep.models import KeepCreateInput


class _Notes:
    def create(self, **_: object) -> "_Notes":
        return self

    def execute(self) -> dict[str, str]:
        return {"name": "notes/note-xyz", "title": "My Note"}


class _Svc:
    def notes(self) -> _Notes:
        return _Notes()


def test_keep_create_records_created_note_name_as_target_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import google_kit.core.audit as audit_mod

    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_mod, "_DEFAULT_AUDIT_PATH", audit_file)

    keep_create(KeepCreateInput(title="My Note", body_text="hi"), service=_Svc())

    records = read_audit(op="keep.create", audit_file=audit_file)
    assert len(records) == 1
    assert records[0]["target_ids"] == ["notes/note-xyz"]
