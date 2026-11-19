"""Live sandbox end-to-end tests for the NEW-API surfaces and WATCH/subscription ops.

Companion to ``test_sandbox_e2e.py`` (the P6 cutover-minimum 9) and
``test_sandbox_e2e_e1.py`` (the E1 existing-scope ops + E3 recipes). These cover
the surfaces that were DEFERRED from those suites because executing them live
needs operator action beyond the already-consented cutover scopes:

  1. NEW APIs. People / Drive Activity / Apps Script need NEW-scope sandbox consent
     (declared-not-granted in ``core/auth.py:GOOGLE_KIT_SCOPES``). Workspace Events
     needs NO new scope — its events.* ops authorize via the already-consented
     drive.readonly (Workspace Events has no dedicated OAuth scope); it is gated on
     a Pub/Sub topic instead:
       * People API v1            — people.get/batch_get/connections/
                                     search_directory/list_directory
       * Drive Activity API v2    — drive_activity.query
       * Apps Script API v1       — script.create/get_content/update_content/
                                     versions/deployments/metrics (+ script.run SKIP)
       * Workspace Events API v1  — events.subscribe/list/patch/delete
                                     (authorizes via drive.readonly; gated by Pub/Sub)
  2. WATCH / subscription ops (need a push destination):
       * Pub/Sub-delivered  — gmail.watch, forms.watches, events.subscribe
       * HTTPS-webhook-delivered — drive.changes_watch, calendar.watch

Gating (every test SKIPS cleanly when its prerequisite is absent — see conftest
``SandboxSkipped -> pytest.skip``):

  GOOGLE_KIT_SANDBOX=1               — base creds gate (require_sandbox); when
                                       unset EVERY test here skips at line 1.
  GOOGLE_KIT_SANDBOX_NEW_SCOPES=1    — set by the operator AFTER consenting the
                                       new-API scopes on the sandbox profile
                                       (People/DriveActivity/AppsScript). Gates the
                                       People/Drive Activity/Apps Script reads.
                                       (Workspace Events needs no new scope — it
                                       authorizes via the already-held drive.readonly.)
  GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC    — fully-qualified Cloud Pub/Sub topic
                                       (projects/<proj>/topics/<topic>) for the
                                       Pub/Sub-delivered watches. Google's push
                                       service account must hold
                                       roles/pubsub.publisher on it (see runbook).
  GOOGLE_KIT_SANDBOX_WEBHOOK_URL     — HTTPS push endpoint on a domain VERIFIED in
                                       the Cloud Console, for the webhook-delivered
                                       watches (drive.changes_watch / calendar.watch).

Teardown discipline (identical to the sibling suites): every created resource is
deleted in a ``finally`` block and the run emits an audit record. Watch teardown
uses the API-appropriate stop/delete (channels().stop for webhook channels,
users().stop for Gmail, forms.watches().delete for Forms, events.delete for
Workspace Events subscriptions).

Run live (full new-API + watch matrix):
  GOOGLE_KIT_SANDBOX=1 GOOGLE_KIT_SANDBOX_PROFILE=sandbox \\
  GOOGLE_KIT_SANDBOX_NEW_SCOPES=1 \\
  GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC=projects/<proj>/topics/<topic> \\
  GOOGLE_KIT_SANDBOX_WEBHOOK_URL=https://<verified-domain>/push \\
    uv run pytest google-kit/tests/test_sandbox_e2e_new_apis.py -v

See ``docs/dev/LIVE-E2E-NEW-APIS.md`` for the full operator runbook.
"""
from __future__ import annotations

import os
import uuid

import pytest

from kp_mcp_testkit.parity import compare
from kp_mcp_testkit.sandbox import (
    SandboxHarness,
    SandboxSkipped,
    require_sandbox,
    sandbox_profile,
)

_RUN_PREFIX = "e2e-new"

# Additional operator-provided prerequisites (beyond GOOGLE_KIT_SANDBOX).
_NEW_SCOPES_VAR = "GOOGLE_KIT_SANDBOX_NEW_SCOPES"
_PUBSUB_TOPIC_VAR = "GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC"
_WEBHOOK_URL_VAR = "GOOGLE_KIT_SANDBOX_WEBHOOK_URL"


# ---------------------------------------------------------------------------
# Gating helpers — each raises SandboxSkipped (conftest -> clean pytest.skip)
# ---------------------------------------------------------------------------


def _require_new_scopes() -> None:
    """Skip cleanly unless the new-API scopes have been consented.

    The operator sets GOOGLE_KIT_SANDBOX_NEW_SCOPES=1 after adding the People /
    Drive Activity / Apps Script scopes to the sandbox consent screen and
    re-consenting the sandbox profile. Until then those scopes are
    declared-not-granted (core/auth.py) and the live calls would 403. (Workspace
    Events is NOT gated here — it authorizes via the already-consented
    drive.readonly and is gated on a Pub/Sub topic instead.)
    """
    if os.environ.get(_NEW_SCOPES_VAR, "").strip() != "1":
        raise SandboxSkipped(
            f"new-API scopes not consented — set {_NEW_SCOPES_VAR}=1 after consenting "
            "People/DriveActivity/AppsScript scopes on the sandbox profile"
        )


def _require_pubsub_topic() -> str:
    """Return the operator-provisioned Pub/Sub topic, or skip cleanly if absent."""
    topic = os.environ.get(_PUBSUB_TOPIC_VAR, "").strip()
    if not topic:
        raise SandboxSkipped(
            f"no Pub/Sub topic — set {_PUBSUB_TOPIC_VAR}=projects/<proj>/topics/<topic> "
            "(Google push service account must hold roles/pubsub.publisher on it)"
        )
    return topic


def _require_webhook_url() -> str:
    """Return the operator-provisioned HTTPS push endpoint, or skip cleanly if absent."""
    url = os.environ.get(_WEBHOOK_URL_VAR, "").strip()
    if not url:
        raise SandboxSkipped(
            f"no push webhook URL — set {_WEBHOOK_URL_VAR}=https://<verified-domain>/<path> "
            "(domain must be verified in the Cloud Console for Drive/Calendar push)"
        )
    return url


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_sandbox_e2e_e1.py)
# ---------------------------------------------------------------------------


def _svc(op: str):
    """Build an authorized service for *op* using the sandbox Keychain profile."""
    from google_kit.core.auth import build_service_for_op

    return build_service_for_op(op, profile=sandbox_profile())


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
    """Create a blank Google Doc; return its file id (uses already-consented drive.file)."""
    from google_kit.services.drive.core import drive_create
    from google_kit.services.drive.models import DriveCreateInput

    res = drive_create(DriveCreateInput(title=run_id, doc_type="doc"), service=drive_svc)
    return res.data.id


# Substrings (matched case-insensitively) that identify a Google Workspace-domain
# requirement — the consumer-account limitation we skip on. Specific enough not to
# mask genuine failures (e.g. INVALID_EVENT_TYPE, quota, auth, a generic 403).
_WORKSPACE_REQUIRED_SIGNALS = (
    "g suite domain user",        # People directory ops (confirmed live 400)
    "gsuite domain user",
    "google workspace account",
    "workspace domain",
    "workspace account",
    "must be a member of",        # org-membership / domain-required reason
)


def _skip_if_workspace_only(exc: Exception) -> None:
    """Convert a Workspace-only 4xx into a clean skip (consumer-account limit).

    People directory ops and Workspace Events Drive subscriptions require a Google
    Workspace domain; a consumer gmail.com sandbox account cannot exercise them
    (same family of limitation as Keep / BD-6).

    IMPORTANT: the kit's ``execute_api_call`` classifies a googleapiclient
    ``HttpError`` into the GoogleKitError taxonomy *before* it reaches the test
    (400 -> ``Validation``, 403 -> ``Permission``), so catching ``HttpError`` here
    would never fire. We inspect the classified kit error (and a raw ``HttpError``
    defensively) and skip ONLY when the message carries the specific
    Workspace-required signal — any other 4xx is a genuine failure and is
    re-raised unchanged (we do NOT mask real errors).
    """
    from googleapiclient.errors import HttpError

    from google_kit.core.errors import GoogleKitError, Permission, Validation

    message = ""
    is_4xx = False
    if isinstance(exc, (Validation, Permission)):  # kit-classified 400 / 403
        message = exc.message or str(exc)
        is_4xx = True
    elif isinstance(exc, HttpError):  # defensive: unclassified raw HttpError
        try:
            is_4xx = int(exc.resp.status) in (400, 403)
        except Exception:
            is_4xx = False
        message = str(exc)
    elif isinstance(exc, GoogleKitError):
        # Other taxonomy classes (Auth/QuotaRateLimit/Transient/NotFound/...) are
        # never a Workspace-domain signal — surface them as genuine failures.
        message = exc.message or str(exc)

    signal = message.lower()
    if is_4xx and any(s in signal for s in _WORKSPACE_REQUIRED_SIGNALS):
        pytest.skip(
            "requires a Google Workspace domain (consumer sandbox account cannot "
            f"exercise this op): {message}"
        )
    raise exc


# ===========================================================================
# People API v1 (new scope: directory.readonly + contacts.readonly)
# ===========================================================================


def test_people_get_self_read() -> None:
    """Live: people.get('people/me') — read-only; assert a resource name comes back."""
    require_sandbox()
    _require_new_scopes()
    harness = SandboxHarness(op="people.get", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.people.core import people_get
    from google_kit.services.people.models import PeopleGetInput

    svc = _svc("people.get")
    res = people_get(PeopleGetInput(resource_name="people/me"), service=svc)
    assert res.data.resource_name, "people.get returned no resource_name"

    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


def test_people_batch_get_self_read() -> None:
    """Live: people.batch_get(['people/me']) — read-only; assert >=1 person."""
    require_sandbox()
    _require_new_scopes()
    harness = SandboxHarness(op="people.batch_get", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.people.core import people_batch_get
    from google_kit.services.people.models import PeopleBatchGetInput

    svc = _svc("people.batch_get")
    res = people_batch_get(PeopleBatchGetInput(resource_names=["people/me"]), service=svc)
    assert res.data.count >= 1, f"expected >=1 person, got {res.data.count}"

    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


def test_people_connections_read_tolerates_empty() -> None:
    """Live: people.connections — read-only; tolerates an empty contact list."""
    require_sandbox()
    _require_new_scopes()
    harness = SandboxHarness(op="people.connections", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.people.core import people_connections
    from google_kit.services.people.models import PeopleConnectionsInput

    svc = _svc("people.connections")
    res = people_connections(PeopleConnectionsInput(page_size=10), service=svc)
    assert res.data.count >= 0 and isinstance(res.data.connections, list)

    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


def test_people_search_directory_read() -> None:
    """Live: people.search_directory — read-only; Workspace-only (skips on consumer)."""
    require_sandbox()
    _require_new_scopes()
    harness = SandboxHarness(op="people.search_directory", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.core.errors import GoogleKitError
    from google_kit.services.people.core import people_search_directory
    from google_kit.services.people.models import PeopleSearchDirectoryInput

    svc = _svc("people.search_directory")
    try:
        res = people_search_directory(
            PeopleSearchDirectoryInput(query="a", page_size=5), service=svc
        )
        assert res.data.count >= 0 and isinstance(res.data.people, list)
    except GoogleKitError as exc:
        _skip_if_workspace_only(exc)

    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


def test_people_list_directory_read() -> None:
    """Live: people.list_directory — read-only; Workspace-only (skips on consumer)."""
    require_sandbox()
    _require_new_scopes()
    harness = SandboxHarness(op="people.list_directory", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.core.errors import GoogleKitError
    from google_kit.services.people.core import people_list_directory
    from google_kit.services.people.models import PeopleListDirectoryInput

    svc = _svc("people.list_directory")
    try:
        res = people_list_directory(PeopleListDirectoryInput(page_size=5), service=svc)
        assert res.data.count >= 0 and isinstance(res.data.people, list)
    except GoogleKitError as exc:
        _skip_if_workspace_only(exc)

    ctx.record_comparison(passed=True)
    ctx.record_cleaned_up()
    harness.emit_audit(ctx)


# ===========================================================================
# Drive Activity API v2 (new scope: drive.activity.readonly)
# ===========================================================================


def test_drive_activity_query_read() -> None:
    """Live: create a Doc → drive_activity.query for that item → tolerate empty → delete.

    Activity indexing is asynchronous, so a freshly-created item may have zero
    activities yet; the test asserts a well-formed (possibly empty) result.
    """
    require_sandbox()
    _require_new_scopes()
    harness = SandboxHarness(op="drive_activity.query", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.drive_activity.core import drive_activity_query
    from google_kit.services.drive_activity.models import DriveActivityQueryInput

    drive_svc = _svc("drive.create")
    activity_svc = _svc("drive_activity.query")
    file_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(file_id)
    try:
        res = drive_activity_query(
            DriveActivityQueryInput(item_name=f"items/{file_id}", page_size=10),
            service=activity_svc,
        )
        assert isinstance(res.data.activities, list)
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        try:
            _drive_delete(drive_svc, file_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


# ===========================================================================
# Apps Script API v1 (new scopes: script.projects[.readonly], script.deployments)
# ===========================================================================


def test_script_create_get_content_lifecycle() -> None:
    """Live: script.create → script.get_content (parity) → best-effort Drive cleanup.

    NOTE: Apps Script v1 has no projects.delete; a standalone project is a Drive
    file. Cleanup attempts a Drive trash/delete (best-effort) — the operator should
    confirm no orphaned ``{run_id}`` script projects remain (greppable by prefix).
    """
    require_sandbox()
    _require_new_scopes()
    harness = SandboxHarness(op="script.create", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.apps_script.core import script_create, script_get_content
    from google_kit.services.apps_script.models import (
        ScriptCreateInput,
        ScriptGetContentInput,
    )

    script_svc = _svc("script.create")
    drive_svc = _svc("drive.create")

    script_id: str | None = None
    try:
        created = script_create(ScriptCreateInput(title=ctx.run_id), service=script_svc)
        script_id = created.data.script_id
        ctx.record_created(script_id)
        assert script_id, "script.create returned no script_id"
        assert created.data.title == ctx.run_id

        content = script_get_content(
            ScriptGetContentInput(script_id=script_id), service=script_svc
        )
        # A new project always carries at least the manifest (appsscript.json).
        assert content.data.script_id == script_id
        assert isinstance(content.data.files, list)

        parity = compare(
            "sandbox-e2e",
            {"script_id": script_id},
            {"script_id": content.data.script_id},
        )
        ctx.record_comparison(passed=parity.match, deviation=parity.diff)
        assert parity.match, f"script create/get-content id mismatch: {parity.diff}"
        ctx.record_cleaned_up()
    finally:
        if script_id:
            try:
                _drive_delete(drive_svc, script_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


def test_script_update_versions_deployments_metrics_lifecycle() -> None:
    """Live: create → update_content → versions/deployments/metrics reads → cleanup."""
    require_sandbox()
    _require_new_scopes()
    harness = SandboxHarness(op="script.update_content", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.services.apps_script.core import (
        script_create,
        script_deployments,
        script_metrics,
        script_update_content,
        script_versions,
    )
    from google_kit.services.apps_script.models import (
        ScriptCreateInput,
        ScriptDeploymentsInput,
        ScriptFileInput,
        ScriptMetricsInput,
        ScriptUpdateContentInput,
        ScriptVersionsInput,
    )

    script_svc = _svc("script.update_content")
    drive_svc = _svc("drive.create")

    script_id: str | None = None
    try:
        created = script_create(ScriptCreateInput(title=ctx.run_id), service=script_svc)
        script_id = created.data.script_id
        ctx.record_created(script_id)
        assert script_id, "script.create returned no script_id"

        # update_content requires the manifest file alongside any source files.
        updated = script_update_content(
            ScriptUpdateContentInput(
                script_id=script_id,
                files=[
                    ScriptFileInput(
                        name="appsscript",
                        type="JSON",
                        source='{"timeZone":"America/New_York","exceptionLogging":"STACKDRIVER"}',
                    ),
                    ScriptFileInput(
                        name="Code",
                        type="SERVER_JS",
                        source="function e2e() { return 'ok'; }",
                    ),
                ],
            ),
            service=script_svc,
        )
        assert updated.data.script_id == script_id

        versions = script_versions(ScriptVersionsInput(script_id=script_id), service=script_svc)
        assert isinstance(versions.data.versions, list)

        deployments = script_deployments(
            ScriptDeploymentsInput(script_id=script_id), service=script_svc
        )
        assert isinstance(deployments.data.deployments, list)

        metrics = script_metrics(
            ScriptMetricsInput(script_id=script_id, metrics_granularity="WEEKLY"),
            service=script_svc,
        )
        assert isinstance(metrics.data.total_executions, list)

        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        if script_id:
            try:
                _drive_delete(drive_svc, script_id)
            except Exception:
                pass
        harness.emit_audit(ctx)


@pytest.mark.skip(
    reason=(
        "script.run: escape-hatch — requires the script deployed as API-executable "
        "in the SAME Cloud project as the OAuth client (not seedable in a generic "
        "sandbox). DEFERRED, mirroring keep/BD-6 and gmail.attachments."
    )
)
def test_script_run_blocked() -> None:  # pragma: no cover
    """DEFERRED: script.run needs an API-executable deployment in the OAuth project."""


# ===========================================================================
# Workspace Events API v1 (authorizes via drive.readonly; gated on Pub/Sub topic)
# ===========================================================================


def test_events_subscription_lifecycle() -> None:
    """Live: events.subscribe (Drive file target → Pub/Sub) → list → patch → delete.

    Authorizes via the already-consented drive.readonly (Workspace Events has no
    dedicated OAuth scope; subscriptions authorize using the target resource's
    scope, and the kit's events.* ops target Drive). Needs a Pub/Sub topic the
    Workspace Events push service account can publish to.

    The target is a single Drive file, so the event type must be file-scoped:
    ``contentChanged`` (a file edit / new revision). Container events like
    ``created``/``moved`` ("a file added/moved to a folder or shared drive") are
    INVALID for a single-file target — Google rejects that pairing with
    EVENT_TYPE_CONFIG_MISMATCH; they need a folder or shared-drive target. A
    single-file ``contentChanged`` subscription is exercisable on a consumer
    gmail.com account (verified live). The ``_skip_if_workspace_only`` guard is a
    safety net only for genuinely Workspace-only targets (e.g. shared drives) — it
    never masks a request-shape/validation error.
    """
    require_sandbox()
    topic = _require_pubsub_topic()
    harness = SandboxHarness(op="events.subscribe", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.core.errors import GoogleKitError
    from google_kit.services.workspace_events.core import (
        events_delete,
        events_list,
        events_patch,
        events_subscribe,
    )
    from google_kit.services.workspace_events.models import (
        EventsDeleteInput,
        EventsListInput,
        EventsPatchInput,
        EventsSubscribeInput,
    )

    drive_svc = _svc("drive.create")
    events_svc = _svc("events.subscribe")
    file_id = _make_blank_doc(drive_svc, ctx.run_id)
    ctx.record_created(file_id)

    target = f"//drive.googleapis.com/files/{file_id}"
    subscription_name: str | None = None
    sub = None
    try:
        try:
            sub = events_subscribe(
                EventsSubscribeInput(
                    target_resource=target,
                    event_types=["google.workspace.drive.file.v3.contentChanged"],
                    pubsub_topic=topic,
                ),
                service=events_svc,
            )
        except GoogleKitError as exc:
            _skip_if_workspace_only(exc)  # raises pytest.skip (4xx) or re-raises
        assert sub is not None and sub.data.name, (
            "events.subscribe returned no Operation/subscription name"
        )

        # Resolve the concrete subscription resource via list (the create returns a
        # long-running Operation whose name is not the subscription name).
        listed = events_list(
            EventsListInput(filter=f"target_resource=\"{target}\""), service=events_svc
        )
        for item in listed.data.subscriptions:
            if item.target_resource == target:
                subscription_name = item.name
                break
        # Fall back to the operation-reported name if list did not surface it yet.
        subscription_name = subscription_name or sub.data.name
        ctx.record_created(subscription_name)

        patched = events_patch(
            EventsPatchInput(name=subscription_name, update_mask="ttl", ttl="3600s"),
            service=events_svc,
        )
        assert patched.data.name

        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        if subscription_name:
            try:
                events_delete(EventsDeleteInput(name=subscription_name), service=events_svc)
            except Exception:
                pass
        try:
            _drive_delete(drive_svc, file_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


# ===========================================================================
# WATCH ops — Pub/Sub-delivered (gate: GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC)
# ===========================================================================


def test_gmail_watch_lifecycle() -> None:
    """Live: gmail.watch (users.watch → Pub/Sub) → assert historyId → users().stop().

    Uses the already-consented gmail.readonly scope; needs a Pub/Sub topic on which
    gmail-api-push@system.gserviceaccount.com holds roles/pubsub.publisher.
    """
    require_sandbox()
    topic = _require_pubsub_topic()
    harness = SandboxHarness(op="gmail.watch", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.core.client import execute_api_call
    from google_kit.services.gmail.core import gmail_watch
    from google_kit.services.gmail.models import GmailWatchInput

    svc = _svc("gmail.watch")
    started = False
    try:
        res = gmail_watch(GmailWatchInput(topic_name=topic, label_ids=["INBOX"]), service=svc)
        started = True
        assert res.data.history_id, "gmail.watch returned no historyId"
        assert res.data.expiration, "gmail.watch returned no expiration"
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        if started:
            try:
                execute_api_call(
                    lambda: svc.users().stop(userId="me").execute(),
                    op="gmail.watch.stop",
                    posture="destructive",
                )
            except Exception:
                pass
        harness.emit_audit(ctx)


def test_forms_watches_lifecycle() -> None:
    """Live: create a Form → forms.watches (→ Pub/Sub) → assert watch → delete watch + form.

    Uses already-consented forms scopes; needs a Pub/Sub topic the Forms push
    service account can publish to. Teardown deletes the watch via the raw
    forms().watches().delete (no first-class delete op in v1), then the form.
    """
    require_sandbox()
    topic = _require_pubsub_topic()
    harness = SandboxHarness(op="forms.watches", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.core.client import execute_api_call
    from google_kit.services.forms.core import forms_create, forms_watches
    from google_kit.services.forms.models import FormsCreateInput, FormsWatchesInput

    forms_svc = _svc("forms.watches")
    drive_svc = _svc("drive.create")
    created = forms_create(FormsCreateInput(title=ctx.run_id), service=forms_svc)
    form_id = created.data.form_id
    ctx.record_created(form_id)

    watch_id: str | None = None
    try:
        res = forms_watches(
            FormsWatchesInput(form_id=form_id, topic_name=topic, event_type="RESPONSES"),
            service=forms_svc,
        )
        watch_id = res.data.watch_id
        assert watch_id, "forms.watches returned no watch id"
        ctx.record_created(watch_id)
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        if watch_id:
            try:
                execute_api_call(
                    lambda: forms_svc.forms()
                    .watches()
                    .delete(formId=form_id, watchId=watch_id)
                    .execute(),
                    op="forms.watches.delete",
                    posture="destructive",
                )
            except Exception:
                pass
        try:
            _drive_delete(drive_svc, form_id)
        except Exception:
            pass
        harness.emit_audit(ctx)


# ===========================================================================
# WATCH ops — HTTPS-webhook-delivered (gate: GOOGLE_KIT_SANDBOX_WEBHOOK_URL)
# ===========================================================================


def test_drive_changes_watch_lifecycle() -> None:
    """Live: drive.changes_watch (changes.watch → HTTPS webhook) → channels().stop().

    Uses already-consented drive.readonly; needs an HTTPS endpoint on a domain
    verified in the Cloud Console. Teardown stops the channel.
    """
    require_sandbox()
    webhook_url = _require_webhook_url()
    harness = SandboxHarness(op="drive.changes_watch", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.core.client import execute_api_call
    from google_kit.services.drive.core import drive_changes, drive_changes_watch
    from google_kit.services.drive.models import DriveChangesInput, DriveChangesWatchInput

    svc = _svc("drive.changes_watch")
    start = drive_changes(DriveChangesInput(), service=svc)
    page_token = start.data.new_start_page_token
    assert page_token, "getStartPageToken returned no token"

    channel_id = f"{ctx.run_id}-{uuid.uuid4().hex[:8]}"
    resource_id: str | None = None
    try:
        res = drive_changes_watch(
            DriveChangesWatchInput(
                page_token=page_token, channel_id=channel_id, address=webhook_url
            ),
            service=svc,
        )
        assert res.data.id == channel_id, f"channel id mismatch: {res.data.id!r}"
        resource_id = res.data.resourceId
        assert resource_id, "drive.changes_watch returned no resourceId"
        ctx.record_created(channel_id)
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        if resource_id:
            try:
                execute_api_call(
                    lambda: svc.channels()
                    .stop(body={"id": channel_id, "resourceId": resource_id})
                    .execute(),
                    op="drive.channels.stop",
                    posture="destructive",
                )
            except Exception:
                pass
        harness.emit_audit(ctx)


def test_calendar_watch_lifecycle() -> None:
    """Live: calendar.watch (events.watch → HTTPS webhook) → channels().stop().

    Uses the already-consented calendar scope; needs an HTTPS endpoint on a domain
    verified in the Cloud Console. Teardown stops the channel.
    """
    require_sandbox()
    webhook_url = _require_webhook_url()
    harness = SandboxHarness(op="calendar.watch", run_id_prefix=_RUN_PREFIX)
    ctx = harness.build_context()

    from google_kit.core.client import execute_api_call
    from google_kit.services.calendar.core import calendar_watch
    from google_kit.services.calendar.models import CalendarWatchInput

    svc = _svc("calendar.watch")
    channel_id = f"{ctx.run_id}-{uuid.uuid4().hex[:8]}"
    resource_id: str | None = None
    try:
        res = calendar_watch(
            CalendarWatchInput(
                calendar_id="primary", channel_id=channel_id, address=webhook_url
            ),
            service=svc,
        )
        assert res.data.id == channel_id, f"channel id mismatch: {res.data.id!r}"
        resource_id = res.data.resource_id
        assert resource_id, "calendar.watch returned no resourceId"
        ctx.record_created(channel_id)
        ctx.record_comparison(passed=True)
        ctx.record_cleaned_up()
    finally:
        if resource_id:
            try:
                execute_api_call(
                    lambda: svc.channels()
                    .stop(body={"id": channel_id, "resourceId": resource_id})
                    .execute(),
                    op="calendar.channels.stop",
                    posture="destructive",
                )
            except Exception:
                pass
        harness.emit_audit(ctx)
