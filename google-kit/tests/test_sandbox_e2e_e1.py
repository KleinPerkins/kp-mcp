"""Live sandbox end-to-end tests for the E1 existing-scope ops + E3 recipes.

Companion to ``test_sandbox_e2e.py`` (the P6 cutover-minimum 9). These exercise
the §7 capability-fill ops that run under the ALREADY-consented sandbox scopes
(no new-scope consent, no Cloud Pub/Sub topic). Every test gates on
GOOGLE_KIT_SANDBOX=1 (SandboxSkipped → pytest.skip when absent).

Run live:
  GOOGLE_KIT_SANDBOX=1 GOOGLE_KIT_SANDBOX_PROFILE=sandbox \\
    uv run pytest google-kit/tests/test_sandbox_e2e_e1.py -v

Out of scope here (kept DEFERRED — declared-not-granted / not seedable):
  * new-API ops (People, Drive Activity, Workspace Events, Apps Script,
    Gmail-write) — need new-scope consent.
  * all watches (drive/calendar/forms/gmail) — need a Cloud Pub/Sub topic.
  * gmail.attachments — needs a message bearing an attachment (cannot be seeded
    without gmail-send, which is new-scope-gated).
  * forms.get_response — needs a human-submitted response (Forms API has no
    create-response method).
"""
from __future__ import annotations

import json

import pytest

from kp_mcp_testkit.sandbox import (
    SandboxHarness,
    require_sandbox,
    sandbox_profile,
)

_RUN_PREFIX = "e2e-e1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _svc(op: str):
    """Build an authorized service for *op* using the sandbox Keychain profile."""
    from google_kit.core.auth import build_service_for_op

    return build_service_for_op(op, profile=sandbox_profile())


def _recipe_resolver():
    """Return a ServiceResolver (api_prefix -> authorized Resource) for recipes."""
    return lambda prefix: _svc(f"{prefix}._recipe")


def _drive_delete(drive_service, file_id: str) -> None:
    """Raw Drive files().delete() — permanent cleanup for any Drive-hosted artifact."""
    from google_kit.core.client import execute_api_call

    execute_api_call(
        lambda: drive_service.files().delete(fileId=file_id).execute(),
        op="drive.delete",
        posture="destructive",
    )


def _drive_get_or_404(drive_service, file_id: str):
    """Return file metadata dict (id,name,trashed), or None if 404 (hard-deleted)."""
    from googleapiclient.errors import HttpError

    try:
        return drive_service.files().get(fileId=file_id, fields="id,name,trashed").execute()
    except HttpError as exc:
        if int(exc.resp.status) == 404:
            return None
        raise


def _make_blank_doc(drive_svc, run_id: str) -> str:
    """Create a blank Google Doc; return its file id."""
    from google_kit.services.drive.core import drive_create
    from google_kit.services.drive.models import DriveCreateInput

    res = drive_create(DriveCreateInput(title=run_id, doc_type="doc"), service=drive_svc)
    return res.data.id


def _make_doc_from_markdown(drive_svc, docs_svc, run_id: str, markdown: str) -> str:
    """Create a Google Doc from markdown; return its doc id."""
    from google_kit.services.docs.core import docs_from_markdown
    from google_kit.services.docs.models import DocsFromMarkdownInput

    res = docs_from_markdown(
        DocsFromMarkdownInput(title=run_id, markdown_content=markdown),
        drive_service=drive_svc,
        docs_service=docs_svc,
    )
    return res.data.doc_id


def _make_spreadsheet(sheets_svc, drive_svc, run_id: str) -> str:
    """Create a one-sheet spreadsheet; return its spreadsheet id."""
    from google_kit.services.sheets.core import sheets_create
    from google_kit.services.sheets.models import SheetsCreateInput

    res = sheets_create(
        SheetsCreateInput(title=run_id, sheet_names=["Sheet1"]),
        service=sheets_svc,
        drive_service=drive_svc,
    )
    return res.data.spreadsheet_id


def _seed_sheet_values(sheets_svc, ss_id: str) -> None:
    """Write a tiny labelled numeric table into Sheet1!A1:C3 (for pivot/format)."""
    from google_kit.core.client import execute_api_call

    body = {"values": [["grp", "n", "v"], ["a", 1, 10], ["b", 2, 20]]}
    execute_api_call(
        lambda: sheets_svc.spreadsheets().values().update(
            spreadsheetId=ss_id, range="Sheet1!A1", valueInputOption="RAW", body=body
        ).execute(),
        op="sheets.write",
        posture="write",
    )


def _first_sheet_id(sheets_svc, ss_id: str) -> int:
    """Return the real sheetId (gid) of the first sheet — API-created sheets are NOT gid 0."""
    meta = sheets_svc.spreadsheets().get(
        spreadsheetId=ss_id, fields="sheets.properties.sheetId"
    ).execute()
    return int(meta["sheets"][0]["properties"]["sheetId"])


# ===========================================================================
# Drive E1 ops
# ===========================================================================


def test_drive_copy_lifecycle() -> None:
    """Live: create a Doc → drive.copy → verify copy exists → delete both."""
    require_sandbox()
    harness = SandboxHarness(op="drive.copy", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive.core import drive_copy
    from google_kit.services.drive.models import DriveCopyInput

    drive_svc = _svc("drive.copy")
    src_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(src_id)
    copy_id: str | None = None
    try:
        res = drive_copy(DriveCopyInput(file_id=src_id, name=f"{ctx.run_id}-copy"), service=drive_svc)
        copy_id = res.data.id
        ctx.record_created(copy_id)
        assert copy_id and copy_id != src_id, "copy returned no distinct id"
        assert res.data.name == f"{ctx.run_id}-copy"
        meta = _drive_get_or_404(drive_svc, copy_id)
        assert meta is not None and meta.get("name") == f"{ctx.run_id}-copy"
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        for fid in (copy_id, src_id):
            if fid:
                try:
                    _drive_delete(drive_svc, fid)
                except Exception:
                    pass
        harness.emit_audit(ctx)


def test_drive_update_lifecycle() -> None:
    """Live: create a Doc → drive.update (rename + star) → verify → delete."""
    require_sandbox()
    harness = SandboxHarness(op="drive.update", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive.core import drive_update
    from google_kit.services.drive.models import DriveUpdateInput

    drive_svc = _svc("drive.update")
    file_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(file_id)
    try:
        new_name = f"{ctx.run_id}-renamed"
        res = drive_update(
            DriveUpdateInput(file_id=file_id, name=new_name, starred=True), service=drive_svc
        )
        assert res.data.name == new_name
        meta = drive_svc.files().get(fileId=file_id, fields="id,name,starred").execute()
        assert meta.get("name") == new_name and meta.get("starred") is True
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, file_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_drive_trash_lifecycle() -> None:
    """Live: create a Doc → drive.trash → verify trashed=True → hard-delete."""
    require_sandbox()
    harness = SandboxHarness(op="drive.trash", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive.core import drive_trash
    from google_kit.services.drive.models import DriveTrashInput

    drive_svc = _svc("drive.trash")
    file_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(file_id)
    try:
        res = drive_trash(DriveTrashInput(file_id=file_id), service=drive_svc)
        assert res.data.trashed is True and res.data.id == file_id
        meta = _drive_get_or_404(drive_svc, file_id)
        assert meta is not None and meta.get("trashed") is True
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, file_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_drive_permissions_lifecycle() -> None:
    """Live: create → permissions.create (anyone/reader) → list → delete perm → delete file."""
    require_sandbox()
    harness = SandboxHarness(op="drive.permissions", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive.core import drive_permissions
    from google_kit.services.drive.models import DrivePermissionsInput

    drive_svc = _svc("drive.permissions")
    file_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(file_id)
    try:
        # Share with "anyone" (link permission — no email is sent to anyone).
        created = drive_permissions(
            DrivePermissionsInput(file_id=file_id, action="create", role="reader", type="anyone"),
            service=drive_svc,
        )
        perm = created.data.permission or {}
        perm_id = perm.get("id")
        assert perm_id, f"permissions.create returned no id: {created.data}"

        listed = drive_permissions(
            DrivePermissionsInput(file_id=file_id, action="list"), service=drive_svc
        )
        ids = {p.get("id") for p in (listed.data.permissions or [])}
        assert perm_id in ids, f"created permission {perm_id} not in list {ids}"

        deleted = drive_permissions(
            DrivePermissionsInput(file_id=file_id, action="delete", permission_id=perm_id),
            service=drive_svc,
        )
        assert deleted.data.deleted is True
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, file_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_drive_comments_lifecycle() -> None:
    """Live: create a Doc → comments.create → comments.list (verify) → delete file."""
    require_sandbox()
    harness = SandboxHarness(op="drive.comments", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive.core import drive_comments
    from google_kit.services.drive.models import DriveCommentsInput

    drive_svc = _svc("drive.comments")
    file_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(file_id)
    try:
        content = f"e2e comment {ctx.run_id}"
        created = drive_comments(
            DriveCommentsInput(file_id=file_id, action="create", content=content),
            service=drive_svc,
        )
        comment_id = (created.data.comment or {}).get("id")
        assert comment_id, f"comments.create returned no id: {created.data}"

        listed = drive_comments(
            DriveCommentsInput(file_id=file_id, action="list"), service=drive_svc
        )
        ids = {c.get("id") for c in (listed.data.comments or [])}
        assert comment_id in ids, f"created comment {comment_id} not in list {ids}"
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, file_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_drive_revisions_read() -> None:
    """Live: create a Doc → drive.revisions list → assert >=1 revision → delete."""
    require_sandbox()
    harness = SandboxHarness(op="drive.revisions", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive.core import drive_revisions
    from google_kit.services.drive.models import DriveRevisionsInput

    drive_svc = _svc("drive.revisions")
    file_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(file_id)
    try:
        res = drive_revisions(DriveRevisionsInput(file_id=file_id), service=drive_svc)
        assert res.data.revisions is not None and len(res.data.revisions) >= 1
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, file_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_drive_changes_read() -> None:
    """Live: drive.changes (no token → start token; then list from it). Read-only."""
    require_sandbox()
    harness = SandboxHarness(op="drive.changes", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive.core import drive_changes
    from google_kit.services.drive.models import DriveChangesInput

    drive_svc = _svc("drive.changes")
    start = drive_changes(DriveChangesInput(), service=drive_svc)
    token = start.data.new_start_page_token
    assert token, "getStartPageToken returned no token"
    # Listing from the fresh token should succeed (changes list may be empty).
    listed = drive_changes(DriveChangesInput(page_token=token), service=drive_svc)
    assert isinstance(listed.data.changes, list)
    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


# ===========================================================================
# Docs E1 op
# ===========================================================================


def test_docs_batch_update_lifecycle() -> None:
    """Live: create a Doc → docs.batch_update (insertText) → verify text → delete."""
    require_sandbox()
    harness = SandboxHarness(op="docs.batch_update", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.docs.core import docs_batch_update
    from google_kit.services.docs.models import DocsBatchUpdateInput

    drive_svc = _svc("drive.create")
    docs_svc = _svc("docs.batch_update")
    doc_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(doc_id)
    try:
        token = f"inserted-{ctx.run_id}"
        res = docs_batch_update(
            DocsBatchUpdateInput(
                document_id=doc_id,
                requests=[{"insertText": {"location": {"index": 1}, "text": f"{token}\n"}}],
            ),
            docs_service=docs_svc,
        )
        assert res.data.document_id == doc_id
        doc = docs_svc.documents().get(documentId=doc_id).execute()
        assert token in json.dumps(doc), "inserted text not found in document body"
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, doc_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


# ===========================================================================
# Sheets E1 ops
# ===========================================================================


def test_sheets_append_lifecycle() -> None:
    """Live: create a spreadsheet → sheets.append → assert cells written → delete."""
    require_sandbox()
    harness = SandboxHarness(op="sheets.append", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.sheets.core import sheets_append
    from google_kit.services.sheets.models import SheetsAppendInput

    sheets_svc = _svc("sheets.append")
    drive_svc = _svc("drive.create")
    ss_id = _make_spreadsheet(sheets_svc, drive_svc, ctx.run_id)
    ctx.record_created(ss_id)
    try:
        res = sheets_append(
            SheetsAppendInput(
                spreadsheet_id=ss_id, range="Sheet1!A1", values=[["alice", 92], ["bob", 78]]
            ),
            service=sheets_svc,
        )
        assert res.data.updated_cells >= 4, f"expected >=4 cells, got {res.data.updated_cells}"
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, ss_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_sheets_pivot_lifecycle() -> None:
    """Live: create + seed a spreadsheet → sheets.pivot → assert reply → delete."""
    require_sandbox()
    harness = SandboxHarness(op="sheets.pivot", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.sheets.core import sheets_pivot
    from google_kit.services.sheets.models import SheetsPivotInput

    sheets_svc = _svc("sheets.pivot")
    drive_svc = _svc("drive.create")
    ss_id = _make_spreadsheet(sheets_svc, drive_svc, ctx.run_id)
    ctx.record_created(ss_id)
    try:
        _seed_sheet_values(sheets_svc, ss_id)
        gid = _first_sheet_id(sheets_svc, ss_id)
        res = sheets_pivot(
            SheetsPivotInput(
                spreadsheet_id=ss_id,
                source_sheet_id=gid,
                source_range={"start_row": 0, "end_row": 3, "start_col": 0, "end_col": 3},
                target_sheet_id=gid,
                target_row=0,
                target_col=5,
                rows=[0],
                values=[{"source_column_offset": 2, "summarize_function": "SUM"}],
            ),
            service=sheets_svc,
        )
        assert res.data.replies_count >= 1
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, ss_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_sheets_conditional_format_lifecycle() -> None:
    """Live: create + seed a spreadsheet → sheets.conditional_format → assert reply → delete."""
    require_sandbox()
    harness = SandboxHarness(op="sheets.conditional_format", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.sheets.core import sheets_conditional_format
    from google_kit.services.sheets.models import SheetsConditionalFormatInput

    sheets_svc = _svc("sheets.conditional_format")
    drive_svc = _svc("drive.create")
    ss_id = _make_spreadsheet(sheets_svc, drive_svc, ctx.run_id)
    ctx.record_created(ss_id)
    try:
        _seed_sheet_values(sheets_svc, ss_id)
        gid = _first_sheet_id(sheets_svc, ss_id)
        res = sheets_conditional_format(
            SheetsConditionalFormatInput(
                spreadsheet_id=ss_id,
                sheet_id=gid,
                range={"start_row": 1, "end_row": 3, "start_col": 1, "end_col": 3},
                condition_type="NUMBER_GREATER",
                condition_values=["1"],
                background_color={"red": 1.0, "green": 0.0, "blue": 0.0},
                bold=True,
            ),
            service=sheets_svc,
        )
        assert res.data.replies_count >= 1
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, ss_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_sheets_metadata_lifecycle() -> None:
    """Live: create a spreadsheet → sheets.metadata (developer metadata) → assert reply → delete."""
    require_sandbox()
    harness = SandboxHarness(op="sheets.metadata", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.sheets.core import sheets_metadata
    from google_kit.services.sheets.models import SheetsMetadataInput

    sheets_svc = _svc("sheets.metadata")
    drive_svc = _svc("drive.create")
    ss_id = _make_spreadsheet(sheets_svc, drive_svc, ctx.run_id)
    ctx.record_created(ss_id)
    try:
        res = sheets_metadata(
            SheetsMetadataInput(
                spreadsheet_id=ss_id,
                metadata_key="e2e_project",
                metadata_value=ctx.run_id,
                visibility="DOCUMENT",
            ),
            service=sheets_svc,
        )
        assert res.data.replies_count >= 1
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, ss_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


# ===========================================================================
# Slides E1 op
# ===========================================================================


def test_slides_thumbnail_read() -> None:
    """Live: create a presentation → slides.thumbnail of slide 1 → assert URL → delete."""
    require_sandbox()
    harness = SandboxHarness(op="slides.thumbnail", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.slides.core import slides_create, slides_thumbnail
    from google_kit.services.slides.models import SlidesCreateInput, SlidesThumbnailInput

    slides_svc = _svc("slides.thumbnail")
    drive_svc = _svc("drive.create")
    created = slides_create(SlidesCreateInput(title=ctx.run_id), service=slides_svc, drive_service=drive_svc)
    pres_id = created.data.presentation_id
    ctx.record_created(pres_id)
    try:
        pres = slides_svc.presentations().get(presentationId=pres_id).execute()
        page_id = pres["slides"][0]["objectId"]
        res = slides_thumbnail(
            SlidesThumbnailInput(presentation_id=pres_id, page_object_id=page_id, thumbnail_size="LARGE"),
            service=slides_svc,
        )
        assert res.data.content_url.startswith("http"), f"no thumbnail url: {res.data}"
        assert res.data.width > 0 and res.data.height > 0
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, pres_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


# ===========================================================================
# Forms E1 ops
# ===========================================================================


def test_forms_publish_lifecycle() -> None:
    """Live: create a form → forms.publish (setPublishSettings) → verify → delete."""
    require_sandbox()
    harness = SandboxHarness(op="forms.publish", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.forms.core import forms_create, forms_publish
    from google_kit.services.forms.models import FormsCreateInput, FormsPublishInput

    forms_svc = _svc("forms.publish")
    drive_svc = _svc("drive.create")
    created = forms_create(FormsCreateInput(title=ctx.run_id), service=forms_svc)
    form_id = created.data.form_id
    ctx.record_created(form_id)
    try:
        res = forms_publish(
            FormsPublishInput(
                form_id=form_id,
                publish_settings={
                    "publishState": {"isPublished": True, "isAcceptingResponses": True}
                },
            ),
            service=forms_svc,
        )
        assert res.data.form_id == form_id
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, form_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


def test_forms_list_responses_read() -> None:
    """Live: create a form → forms.list_responses (empty-tolerant) → delete.

    NOTE: forms.get_response is NOT live-validatable in the sandbox — it needs a
    human-submitted response id and the Forms API has no create-response method.
    """
    require_sandbox()
    harness = SandboxHarness(op="forms.list_responses", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.forms.core import forms_create, forms_list_responses
    from google_kit.services.forms.models import FormsCreateInput, FormsListResponsesInput

    forms_svc = _svc("forms.list_responses")
    drive_svc = _svc("drive.create")
    created = forms_create(FormsCreateInput(title=ctx.run_id), service=forms_svc)
    form_id = created.data.form_id
    ctx.record_created(form_id)
    try:
        res = forms_list_responses(FormsListResponsesInput(form_id=form_id), service=forms_svc)
        assert res.data.count >= 0 and isinstance(res.data.responses, list)
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, form_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


# ===========================================================================
# Gmail E1 ops
# ===========================================================================


def test_gmail_history_read() -> None:
    """Live: read current historyId from profile → gmail.history (empty-tolerant)."""
    require_sandbox()
    harness = SandboxHarness(op="gmail.history", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.gmail.core import gmail_history
    from google_kit.services.gmail.models import GmailHistoryInput

    svc = _svc("gmail.history")
    profile = svc.users().getProfile(userId="me").execute()
    start_history_id = str(profile["historyId"])
    res = gmail_history(GmailHistoryInput(start_history_id=start_history_id), service=svc)
    assert isinstance(res.data.history, list)  # empty is valid (no new history since now)
    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


@pytest.mark.skip(
    reason=(
        "gmail.attachments: needs a message bearing an attachment, which cannot be "
        "seeded under existing scopes (gmail-send is new-scope-gated). DEFERRED."
    )
)
def test_gmail_attachments_blocked() -> None:  # pragma: no cover
    """DEFERRED: no seedable attachment under existing consented scopes."""


@pytest.mark.skip(
    reason=(
        "forms.get_response: needs a human-submitted response id; the Forms API has "
        "no create-response method, so it cannot be seeded in the sandbox. DEFERRED."
    )
)
def test_forms_get_response_blocked() -> None:  # pragma: no cover
    """DEFERRED: no seedable form response in the sandbox."""


# ===========================================================================
# E3 recipes (saga-guarded composition)
# ===========================================================================


def test_recipe_build_then_share_completed() -> None:
    """Live: build_then_share (markdown→doc, then anyone/reader share) → completed."""
    require_sandbox()
    harness = SandboxHarness(op="recipes.build_then_share", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.recipes.core import recipe_build_then_share
    from google_kit.services.recipes.models import BuildThenShareInput

    drive_svc = _svc("drive.create")
    doc_id: str | None = None
    try:
        res = recipe_build_then_share(
            BuildThenShareInput(
                markdown_content=f"# {ctx.run_id}\n\nbuilt by e2e recipe.\n",
                title=ctx.run_id,
                share_with="",  # falsy → anyone-link share, no email sent
                role="reader",
                type="anyone",
            ),
            service=_recipe_resolver(),
        )
        assert res.data.status == "completed", f"recipe rolled back unexpectedly: {res.warnings}"
        doc_id = res.data.doc_id
        ctx.record_created(doc_id)
        assert doc_id and _drive_get_or_404(drive_svc, doc_id) is not None
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        if doc_id:
            try:
                _drive_delete(drive_svc, doc_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


def test_recipe_build_then_share_saga_rollback() -> None:
    """Live: induce a share-step failure → assert LIFO compensation trashed the doc.

    Forces the second saga step (drive.permissions.create) to fail with an invalid
    role AFTER the doc is created, then asserts the recipe surfaced status=
    "rolled_back" and that the just-created Doc was actually trashed in Drive.
    """
    require_sandbox()
    harness = SandboxHarness(op="recipes.build_then_share", run_id_prefix=f"{_RUN_PREFIX}-rollback")
    ctx = harness.build_context()

    from google_kit.services.recipes.core import recipe_build_then_share
    from google_kit.services.recipes.models import BuildThenShareInput

    drive_svc = _svc("drive.create")
    doc_id: str | None = None
    try:
        res = recipe_build_then_share(
            BuildThenShareInput(
                markdown_content=f"# {ctx.run_id}\n\nshould be rolled back.\n",
                title=ctx.run_id,
                share_with="",
                role="not_a_role",  # invalid → permissions.create 400 at the share step
                type="anyone",
            ),
            service=_recipe_resolver(),
        )
        assert res.data.status == "rolled_back", f"expected rollback, got {res.data.status}"
        assert res.meta.saga_compensated is True, "saga_compensated flag not set"
        assert res.warnings and "rolled back" in res.warnings[0]
        doc_id = res.data.doc_id
        assert doc_id, "rollback should still surface the created doc_id"
        ctx.record_created(doc_id)
        # The LIFO compensation must have trashed the real Drive file.
        meta = _drive_get_or_404(drive_svc, doc_id)
        assert meta is None or meta.get("trashed") is True, (
            f"compensation did not trash the doc: {meta}"
        )
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        if doc_id:
            try:
                _drive_delete(drive_svc, doc_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


def test_recipe_template_merge_completed() -> None:
    """Live: template_merge (copy a {{NAME}} template, replace) → completed → delete both."""
    require_sandbox()
    harness = SandboxHarness(op="recipes.template_merge", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.recipes.core import recipe_template_merge
    from google_kit.services.recipes.models import TemplateMergeInput

    drive_svc = _svc("drive.create")
    docs_svc = _svc("docs.from_markdown")
    template_id = _make_doc_from_markdown(
        drive_svc, docs_svc, f"{ctx.run_id}-tmpl", f"Hello {{{{NAME}}}} — {ctx.run_id}\n"
    )
    ctx.record_created(template_id)
    merged_id: str | None = None
    try:
        res = recipe_template_merge(
            TemplateMergeInput(
                template_id=template_id,
                replacements={"{{NAME}}": "World"},
                new_name=f"{ctx.run_id}-merged",
            ),
            service=_recipe_resolver(),
        )
        assert res.data.status == "completed", f"template_merge rolled back: {res.warnings}"
        assert res.data.replacements_applied >= 1
        merged_id = res.data.doc_id
        ctx.record_created(merged_id)
        merged = docs_svc.documents().get(documentId=merged_id).execute()
        body = json.dumps(merged)
        assert "World" in body and "{{NAME}}" not in body, "placeholder not replaced in copy"
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        for fid in (merged_id, template_id):
            if fid:
                try:
                    _drive_delete(drive_svc, fid)
                except Exception:
                    pass
        harness.emit_audit(ctx)


def test_recipe_hydrate_then_refine_completed() -> None:
    """Live: hydrate_then_refine (read a Doc, then apply batchUpdate) → completed → delete."""
    require_sandbox()
    harness = SandboxHarness(op="recipes.hydrate_then_refine", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.recipes.core import recipe_hydrate_then_refine
    from google_kit.services.recipes.models import HydrateThenRefineInput

    drive_svc = _svc("drive.create")
    docs_svc = _svc("docs.batch_update")
    doc_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(doc_id)
    try:
        token = f"refined-{ctx.run_id}"
        res = recipe_hydrate_then_refine(
            HydrateThenRefineInput(
                document_id=doc_id,
                requests=[{"insertText": {"location": {"index": 1}, "text": f"{token}\n"}}],
            ),
            service=_recipe_resolver(),
        )
        assert res.data.status == "completed", f"hydrate_then_refine rolled back: {res.warnings}"
        assert res.data.requests_applied >= 1
        doc = docs_svc.documents().get(documentId=doc_id).execute()
        assert token in json.dumps(doc), "refine text not found in document"
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, doc_id)
        except Exception:
            pass
        harness.emit_audit(ctx)
