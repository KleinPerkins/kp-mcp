"""Live sandbox end-to-end tests for google-kit Phase 6.

These tests make REAL Google API calls against a sandbox credential set.
Every test gates on GOOGLE_KIT_SANDBOX=1; when absent, the conftest hook
converts SandboxSkipped → pytest.skip (clean, no failure).

Lifecycle for each mutating op:
  1. require_sandbox() / harness.build_context() — skip if no creds.
  2. Build authorized service via build_service_for_op(op, profile=sandbox_profile()).
  3. Create (run_id-prefixed name).
  4. Read back, semantic-compare create response vs read-back response.
  5. Delete / cleanup in try/finally.
  6. Verify artifact is gone (read-back raises NotFound or similar).
  7. emit_audit(ctx).

Ops covered:
  calendar.create  → calendar.delete      (destructive; scope: calendar)
  tasks.create     → tasks.delete         (destructive; scope: tasks)
  drive.create     → files().delete(...)  (no drive.delete op; scope: drive.file)
  docs.from_markdown → files().delete(..) (Drive file; scope: documents + drive.file)
  sheets.create    → files().delete(...)  (Drive file; scope: spreadsheets)
  slides.create    → files().delete(...)  (Drive file; scope: presentations)
  forms.create     → files().delete(...)  (Drive file; scope: forms.body)
  gmail.profile                           (read-only; scope: gmail.readonly)
  keep             SKIP — consumer gmail.com test account cannot access the Keep
                   API (Workspace + allowlist required, BD-6); keep scope
                   intentionally excluded from GOOGLE_KIT_SCOPES.

Run live:
  GOOGLE_KIT_SANDBOX=1 GOOGLE_KIT_SANDBOX_PROFILE=sandbox \\
    uv run pytest google-kit/tests/test_sandbox_e2e.py -v
"""
from __future__ import annotations

import pytest

from kp_mcp_testkit.parity import compare
from kp_mcp_testkit.sandbox import (
    SANDBOX_SKIP_REASON,
    SandboxHarness,
    require_sandbox,
    sandbox_profile,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUN_PREFIX = "p6-e2e"


def _svc(op: str):
    """Build an authorized service for *op* using the sandbox Keychain profile."""
    from google_kit.core.auth import build_service_for_op

    return build_service_for_op(op, profile=sandbox_profile())


def _drive_delete(drive_service, file_id: str) -> None:
    """Raw Drive files().delete() — used to clean up all Drive-hosted artifacts."""
    from google_kit.core.client import execute_api_call

    execute_api_call(
        lambda: drive_service.files().delete(fileId=file_id).execute(),
        op="drive.delete",
        posture="destructive",
    )


def _drive_get_or_404(drive_service, file_id: str):
    """Return the file metadata dict, or None if 404 (deleted)."""
    from googleapiclient.errors import HttpError

    try:
        return drive_service.files().get(fileId=file_id, fields="id,name,trashed").execute()
    except HttpError as exc:
        if int(exc.resp.status) == 404:
            return None
        raise


# ---------------------------------------------------------------------------
# calendar.create → calendar.delete
# ---------------------------------------------------------------------------


def test_calendar_create_delete_lifecycle() -> None:
    """Live: create a calendar event → read back → delete → verify gone."""
    require_sandbox()
    harness = SandboxHarness(op="calendar.create", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.calendar.core import calendar_create, calendar_delete
    from google_kit.services.calendar.models import (
        CalendarCreateInput,
        CalendarDeleteInput,
    )

    svc = _svc("calendar.create")

    inp = CalendarCreateInput(
        summary=f"{ctx.run_id}",
        start="2099-01-15T10:00:00Z",
        end="2099-01-15T10:30:00Z",
        description="p6 sandbox e2e — safe to delete",
    )

    event_id: str | None = None
    try:
        result = calendar_create(inp, service=svc)
        event_id = result.data.id
        ctx.record_created(event_id)

        assert event_id, "calendar.create returned no event id"
        assert result.data.summary == inp.summary

        # Read back via raw API and semantic-compare key fields
        raw_event = svc.events().get(calendarId="primary", eventId=event_id).execute()
        create_snapshot = {
            "summary": result.data.summary,
            "start": result.data.start,
        }
        readback_snapshot = {
            "summary": raw_event.get("summary"),
            "start": raw_event.get("start", {}),
        }
        parity = compare("sandbox-e2e", create_snapshot, readback_snapshot)
        ctx.record_comparison(passed=parity.match, deviation=parity.diff)
        assert parity.match, f"calendar create/read-back mismatch: {parity.diff}"

        # Delete
        del_inp = CalendarDeleteInput(event_id=event_id, calendar_id="primary")
        calendar_delete(del_inp, service=svc)

        # Verify cleanup: read-back should now return status=cancelled or raise 410
        from googleapiclient.errors import HttpError as _HttpError

        try:
            after = svc.events().get(calendarId="primary", eventId=event_id).execute()
            # Calendar API typically returns status=cancelled rather than 404
            assert after.get("status") == "cancelled", (
                f"expected cancelled after delete, got status={after.get('status')!r}"
            )
        except _HttpError as exc:
            assert int(exc.resp.status) in (404, 410), (
                f"unexpected HTTP {exc.resp.status} on post-delete read"
            )

        ctx.record_cleaned_up()
    finally:
        if event_id and not ctx.audit.cleaned_up:
            try:
                from google_kit.services.calendar.models import CalendarDeleteInput as _CDI

                calendar_delete(_CDI(event_id=event_id, calendar_id="primary"), service=svc)
            except Exception:
                pass
        harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# tasks.create → tasks.delete
# ---------------------------------------------------------------------------


def test_tasks_create_delete_lifecycle() -> None:
    """Live: create a task → read back → delete → verify gone."""
    require_sandbox()
    harness = SandboxHarness(op="tasks.create", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.tasks.core import tasks_create, tasks_delete
    from google_kit.services.tasks.models import TasksCreateInput, TasksDeleteInput

    svc = _svc("tasks.create")

    inp = TasksCreateInput(
        title=f"{ctx.run_id}",
        notes="p6 sandbox e2e — safe to delete",
    )

    task_id: str | None = None
    try:
        result = tasks_create(inp, service=svc)
        task_id = result.data.id
        ctx.record_created(task_id)

        assert task_id, "tasks.create returned no task id"
        assert result.data.title == inp.title

        # Read back
        raw_task = svc.tasks().get(tasklist="@default", task=task_id).execute()
        create_snapshot = {"title": result.data.title, "status": result.data.status}
        readback_snapshot = {
            "title": raw_task.get("title"),
            "status": raw_task.get("status"),
        }
        parity = compare("sandbox-e2e", create_snapshot, readback_snapshot)
        ctx.record_comparison(passed=parity.match, deviation=parity.diff)
        assert parity.match, f"tasks create/read-back mismatch: {parity.diff}"

        # Delete
        del_inp = TasksDeleteInput(task_id=task_id, tasklist="@default")
        tasks_delete(del_inp, service=svc)

        # Verify cleanup: Tasks API soft-deletes — tasks.get returns the resource
        # with "deleted": true rather than 404.  Accept either form.
        from googleapiclient.errors import HttpError as _HttpError

        try:
            after = svc.tasks().get(tasklist="@default", task=task_id).execute()
            assert after.get("deleted") is True, (
                f"expected deleted=True after task delete, got {after}"
            )
        except _HttpError as exc:
            assert int(exc.resp.status) == 404, (
                f"unexpected HTTP {exc.resp.status} on post-delete read"
            )

        ctx.record_cleaned_up()
    finally:
        if task_id and not ctx.audit.cleaned_up:
            try:
                from google_kit.services.tasks.models import TasksDeleteInput as _TDI

                tasks_delete(_TDI(task_id=task_id, tasklist="@default"), service=svc)
            except Exception:
                pass
        harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# drive.create → files().delete(...)
# ---------------------------------------------------------------------------


def test_drive_create_delete_lifecycle() -> None:
    """Live: create a Drive doc → read back metadata → delete via raw API."""
    require_sandbox()
    harness = SandboxHarness(op="drive.create", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive.core import drive_create
    from google_kit.services.drive.models import DriveCreateInput

    drive_svc = _svc("drive.create")

    inp = DriveCreateInput(title=f"{ctx.run_id}", doc_type="doc")

    file_id: str | None = None
    try:
        result = drive_create(inp, service=drive_svc)
        file_id = result.data.id
        ctx.record_created(file_id)

        assert file_id, "drive.create returned no file id"
        assert result.data.doc_type == "doc"

        # Read back metadata
        raw_meta = drive_svc.files().get(
            fileId=file_id, fields="id,name,mimeType"
        ).execute()
        create_snapshot = {"title": result.data.title, "doc_type": result.data.doc_type}
        readback_snapshot = {
            "title": raw_meta.get("name"),
            # mimeType application/vnd.google-apps.document == "doc"
            "doc_type": "doc",
        }
        parity = compare("sandbox-e2e", create_snapshot, readback_snapshot)
        ctx.record_comparison(passed=parity.match, deviation=parity.diff)
        assert parity.match, f"drive create/read-back mismatch: {parity.diff}"

        # Delete via raw Drive API (no drive.delete op)
        _drive_delete(drive_svc, file_id)

        # Verify cleanup
        after = _drive_get_or_404(drive_svc, file_id)
        assert after is None or after.get("trashed") is True, (
            f"file {file_id!r} still accessible after delete: {after}"
        )
        ctx.record_cleaned_up()
    finally:
        if file_id and not ctx.audit.cleaned_up:
            try:
                _drive_delete(drive_svc, file_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# docs.from_markdown → files().delete(...)
# ---------------------------------------------------------------------------


def test_docs_from_markdown_create_delete_lifecycle() -> None:
    """Live: create a Google Doc from markdown → read back → delete."""
    require_sandbox()
    harness = SandboxHarness(op="docs.from_markdown", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.docs.core import docs_from_markdown
    from google_kit.services.docs.models import DocsFromMarkdownInput

    drive_svc = _svc("drive.create")
    docs_svc = _svc("docs.from_markdown")

    inp = DocsFromMarkdownInput(
        title=f"{ctx.run_id}",
        markdown_content=f"# {ctx.run_id}\n\np6 sandbox e2e — safe to delete.\n",
    )

    doc_id: str | None = None
    try:
        result = docs_from_markdown(inp, drive_service=drive_svc, docs_service=docs_svc)
        doc_id = result.data.doc_id
        ctx.record_created(doc_id)

        assert doc_id, "docs.from_markdown returned no doc id"
        assert result.data.title == inp.title

        # Read back metadata via Drive
        raw_meta = drive_svc.files().get(
            fileId=doc_id, fields="id,name,mimeType"
        ).execute()
        create_snapshot = {"title": result.data.title}
        readback_snapshot = {"title": raw_meta.get("name")}
        parity = compare("sandbox-e2e", create_snapshot, readback_snapshot)
        ctx.record_comparison(passed=parity.match, deviation=parity.diff)
        assert parity.match, f"docs create/read-back mismatch: {parity.diff}"

        # Delete
        _drive_delete(drive_svc, doc_id)

        after = _drive_get_or_404(drive_svc, doc_id)
        assert after is None or after.get("trashed") is True, (
            f"doc {doc_id!r} still accessible after delete"
        )
        ctx.record_cleaned_up()
    finally:
        if doc_id and not ctx.audit.cleaned_up:
            try:
                _drive_delete(drive_svc, doc_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# sheets.create → files().delete(...)
# ---------------------------------------------------------------------------


def test_sheets_create_delete_lifecycle() -> None:
    """Live: create a spreadsheet → read back → delete."""
    require_sandbox()
    harness = SandboxHarness(op="sheets.create", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.sheets.core import sheets_create
    from google_kit.services.sheets.models import SheetsCreateInput

    sheets_svc = _svc("sheets.create")
    drive_svc = _svc("drive.create")

    inp = SheetsCreateInput(title=f"{ctx.run_id}", sheet_names=["Sheet1"])

    ss_id: str | None = None
    try:
        result = sheets_create(inp, service=sheets_svc, drive_service=drive_svc)
        ss_id = result.data.spreadsheet_id
        ctx.record_created(ss_id)

        assert ss_id, "sheets.create returned no spreadsheet id"
        assert result.data.title == inp.title

        # Read back metadata via Drive
        raw_meta = drive_svc.files().get(
            fileId=ss_id, fields="id,name,mimeType"
        ).execute()
        create_snapshot = {"title": result.data.title}
        readback_snapshot = {"title": raw_meta.get("name")}
        parity = compare("sandbox-e2e", create_snapshot, readback_snapshot)
        ctx.record_comparison(passed=parity.match, deviation=parity.diff)
        assert parity.match, f"sheets create/read-back mismatch: {parity.diff}"

        _drive_delete(drive_svc, ss_id)

        after = _drive_get_or_404(drive_svc, ss_id)
        assert after is None or after.get("trashed") is True
        ctx.record_cleaned_up()
    finally:
        if ss_id and not ctx.audit.cleaned_up:
            try:
                _drive_delete(drive_svc, ss_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# slides.create → files().delete(...)
# ---------------------------------------------------------------------------


def test_slides_create_delete_lifecycle() -> None:
    """Live: create a presentation → read back → delete."""
    require_sandbox()
    harness = SandboxHarness(op="slides.create", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.slides.core import slides_create
    from google_kit.services.slides.models import SlidesCreateInput

    slides_svc = _svc("slides.create")
    drive_svc = _svc("drive.create")

    inp = SlidesCreateInput(title=f"{ctx.run_id}")

    pres_id: str | None = None
    try:
        result = slides_create(inp, service=slides_svc, drive_service=drive_svc)
        pres_id = result.data.presentation_id
        ctx.record_created(pres_id)

        assert pres_id, "slides.create returned no presentation id"
        assert result.data.title == inp.title

        raw_meta = drive_svc.files().get(
            fileId=pres_id, fields="id,name,mimeType"
        ).execute()
        create_snapshot = {"title": result.data.title}
        readback_snapshot = {"title": raw_meta.get("name")}
        parity = compare("sandbox-e2e", create_snapshot, readback_snapshot)
        ctx.record_comparison(passed=parity.match, deviation=parity.diff)
        assert parity.match, f"slides create/read-back mismatch: {parity.diff}"

        _drive_delete(drive_svc, pres_id)

        after = _drive_get_or_404(drive_svc, pres_id)
        assert after is None or after.get("trashed") is True
        ctx.record_cleaned_up()
    finally:
        if pres_id and not ctx.audit.cleaned_up:
            try:
                _drive_delete(drive_svc, pres_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# forms.create → files().delete(...)
# ---------------------------------------------------------------------------


def test_forms_create_delete_lifecycle() -> None:
    """Live: create a Google Form → read back → delete via Drive."""
    require_sandbox()
    harness = SandboxHarness(op="forms.create", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.forms.core import forms_create
    from google_kit.services.forms.models import FormsCreateInput

    forms_svc = _svc("forms.create")
    drive_svc = _svc("drive.create")

    inp = FormsCreateInput(
        title=f"{ctx.run_id}",
        description="p6 sandbox e2e — safe to delete",
    )

    form_id: str | None = None
    try:
        result = forms_create(inp, service=forms_svc)
        form_id = result.data.form_id
        ctx.record_created(form_id)

        assert form_id, "forms.create returned no form id"
        assert result.data.title == inp.title

        # Read back title via Forms API: Drive files().name reflects `documentTitle`
        # (not set by default), while `info.title` is the canonical form title.
        raw_form = forms_svc.forms().get(formId=form_id).execute()
        create_snapshot = {"title": result.data.title}
        readback_snapshot = {"title": (raw_form.get("info") or {}).get("title", "")}
        parity = compare("sandbox-e2e", create_snapshot, readback_snapshot)
        ctx.record_comparison(passed=parity.match, deviation=parity.diff)
        assert parity.match, f"forms create/read-back mismatch: {parity.diff}"

        _drive_delete(drive_svc, form_id)

        after = _drive_get_or_404(drive_svc, form_id)
        assert after is None or after.get("trashed") is True
        ctx.record_cleaned_up()
    finally:
        if form_id and not ctx.audit.cleaned_up:
            try:
                _drive_delete(drive_svc, form_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# gmail.profile  (read-only; no mutation, no cleanup needed)
# ---------------------------------------------------------------------------


def test_gmail_profile_read() -> None:
    """Live: fetch Gmail profile — read-only, tolerates any valid response."""
    require_sandbox()
    harness = SandboxHarness(op="gmail.profile", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.gmail.core import gmail_profile
    from google_kit.services.gmail.models import GmailProfileInput

    svc = _svc("gmail.profile")

    result = gmail_profile(GmailProfileInput(), service=svc)

    assert result.data.email_address == "[REDACTED]", (
        "gmail.profile must redact email address"
    )
    assert result.data.messages_total >= 0
    assert result.data.threads_total >= 0

    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# gmail.list  (read-only; graceful skip if inbox empty)
# ---------------------------------------------------------------------------


def test_gmail_list_read_tolerates_empty() -> None:
    """Live: list Gmail messages — tolerates empty inbox (skips gracefully)."""
    require_sandbox()
    harness = SandboxHarness(op="gmail.list", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.gmail.core import gmail_list
    from google_kit.services.gmail.models import GmailListInput

    svc = _svc("gmail.list")

    result = gmail_list(GmailListInput(max_results=1), service=svc)

    # Tolerate empty inbox
    assert result.data.count >= 0
    assert isinstance(result.data.messages, list)

    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


# ---------------------------------------------------------------------------
# keep  — SKIP (consumer gmail.com cannot access Keep API; BD-6)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "keep: consumer gmail.com test account cannot access the Keep API "
        "(Workspace + explicit allowlist required, BD-6). "
        "keep scope is intentionally excluded from GOOGLE_KIT_SCOPES."
    )
)
def test_keep_sandbox_availability() -> None:  # pragma: no cover
    """Placeholder: Keep API is excluded from the sandbox test matrix.

    keep scope is intentionally absent from GOOGLE_KIT_SCOPES. A consumer
    gmail.com account cannot access the Keep API without Workspace enrollment
    and an explicit allowlist entry (BD-6). No live test is possible.
    """
