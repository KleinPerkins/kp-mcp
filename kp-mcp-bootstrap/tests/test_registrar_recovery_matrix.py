"""ADR REC-05: exact state pairs, both dispositions, and inverse recovery.

All state is synthetic and confined to qualified disposable fixture roots.
Snapshots include private bytes so every refusal proves it did not mutate state.
"""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import base64
import json

import pytest

from kp_mcp_bootstrap.registrars import (
    CursorRegistrar, MigrationEvidence, Outcome, ReasonCode, RecoveryDisposition,
    RegistrarError, RegistrationDefinition, SourceIdentity, fixture_approval,
    fixture_context, operation_ref,
)
from kp_mcp_bootstrap.registrars.contracts import digest_bytes, digest_value
from kp_mcp_bootstrap.registrars.state import StateStore, inspect_target


def definition(revision="a", command="/opt/fixture/matrix"):
    return RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:matrix", revision * 40, "matrix"),
        command=command, args=(),
    )


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def saved_images(fixture, prepared):
    record = json.loads((fixture.state_directory / f"prepared-{prepared.record_id}.json").read_bytes())
    return tuple(None if record[key] is None else base64.b64decode(record[key])
                 for key in ("config_preimage", "config_postimage", "receipt_preimage", "receipt_postimage"))


def set_image(path, data):
    if data is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(data)
        path.chmod(0o600)


@contextmanager
def scenario(tmp_path, kind):
    registrar = CursorRegistrar()
    desired = definition()
    with fixture_context(registrar, desired, fixture_root=tmp_path) as fixture:
        if kind in {"unregister", "retire", "update", "zero", "rollback"}:
            initial = registrar.prepare(registrar.preview(fixture.config_path, desired, context=fixture.context))
            assert registrar.apply(initial, fixture_approval(initial)).outcome is Outcome.APPLIED
        if kind == "adopt":
            fixture.config_path.write_text(json.dumps({"mcpServers": {"matrix": {"command": "/opt/fixture/matrix", "args": []}}}))
            evidence = MigrationEvidence(
                evidence_id="fixture-migration", source_owner=desired.source_owner,
                connection_id=desired.connection_id, source_revision=desired.source_revision,
                host=fixture.context.host, scope=fixture.context.scope, native_name=desired.native_name,
                target_id=inspect_target(fixture.config_path).target_id,
                whole_file_digest=digest_bytes(fixture.config_path.read_bytes()),
                owned_leaf_digests=(("/args", digest_value([])), ("/command", digest_value("/opt/fixture/matrix"))),
                provenance_reference="fixture-only", retiring_writer_handoff="retired-fixture-writer",
            )
            fixture = replace(fixture, context=replace(fixture.context, migration_evidence=evidence))
        if kind == "update":
            desired = definition("b", "/opt/fixture/updated")
            fixture = replace(fixture, context=replace(fixture.context, source_revision=desired.source_revision,
                                                       definition_digest=desired.digest))
        if kind == "retire":
            fixture.config_path.write_text('{"mcpServers":{}}\n')
        if kind in {"unregister", "retire"}:
            preview = registrar.preview_unregister(fixture.config_path, context=fixture.context)
        elif kind == "rollback":
            preview = registrar.rollback(operation_ref(initial), context=fixture.context)
        else:
            preview = registrar.preview(fixture.config_path, desired, context=fixture.context)
        original = registrar.prepare(preview)
        store = StateStore(fixture.context)
        yield registrar, fixture, original, fixture_approval(original), store, saved_images(fixture, original)


def reach(registrar, original, approval, phase):
    def interrupt(step):
        if step == phase:
            raise RuntimeError("fixture durable-step interruption")
    registrar._fault = interrupt if phase else lambda _step: None
    result = registrar.apply(original, approval)
    registrar._fault = lambda _step: None
    assert result.outcome is (Outcome.RECOVERY_REQUIRED if phase else
                              Outcome.ROLLED_BACK if original.action.value == "rollback" else
                              Outcome.NO_CHANGE if not result.config_changed and not result.receipt_id else Outcome.APPLIED)
    return result


def assert_pair(fixture, store, images, *, final):
    c0, c1, r0, r1 = images
    expected_c, expected_r = (c1, r1) if final else (c0, r0)
    actual_c = fixture.config_path.read_bytes() if fixture.config_path.exists() else None
    assert actual_c == expected_c
    assert store.read_optional(store.receipt_path()) == expected_r


KINDS = ("register", "adopt", "unregister", "retire", "update", "rollback")
PENDING = ("c0_r0_p", "c1_r0_p", "c1_r1_p")
PHASE = {"c0_r0_p": "journal_prepared", "c1_r0_p": "config_replaced", "c1_r1_p": "receipt_verified"}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("row", PENDING)
@pytest.mark.parametrize("disposition", list(RecoveryDisposition))
def test_pending_transition_table(tmp_path, kind, row, disposition):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        reach(registrar, original, approval, PHASE[row])
        c0, c1, r0, r1 = images
        current_c = fixture.config_path.read_bytes() if fixture.config_path.exists() else None
        current_r = store.read_optional(store.receipt_path())
        cancel_allowed = current_c == c0 and current_r == r0
        before = snapshot(fixture.root)
        if disposition is RecoveryDisposition.CANCEL and not cancel_allowed:
            with pytest.raises(RegistrarError) as caught:
                registrar.prepare_recovery(original, disposition)
            assert caught.value.code is ReasonCode.RECOVERY_CONFLICT
            assert snapshot(fixture.root) == before
            return
        recovery = registrar.prepare_recovery(original, disposition)
        result = registrar.recover(recovery, disposition, fixture_approval(recovery))
        assert result.outcome is (Outcome.CANCELLED if disposition is RecoveryDisposition.CANCEL else Outcome.RECOVERED)
        assert result.config_changed is (disposition is RecoveryDisposition.COMPLETE and current_c != c1)
        assert result.state_changed is True
        assert_pair(fixture, store, images, final=disposition is RecoveryDisposition.COMPLETE)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("disposition", list(RecoveryDisposition))
def test_committed_transition_table(tmp_path, kind, disposition):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        registrar.apply(original, approval)
        before = snapshot(fixture.root)
        if disposition is RecoveryDisposition.CANCEL:
            with pytest.raises(RegistrarError):
                registrar.recover(original, disposition, approval)
        else:
            result = registrar.recover(original, disposition, approval)
            assert result.config_changed is False and result.state_changed is False
            assert_pair(fixture, store, images, final=True)
        assert snapshot(fixture.root) == before


INVALID_ROWS = ("third_config", "third_receipt", "missing_journal", "invalid_journal", "altered_journal", "terminal_third_config", "terminal_third_receipt", "terminal_corrupt")


@pytest.mark.parametrize("kind", ["register", "adopt", "update"])
@pytest.mark.parametrize("row", INVALID_ROWS)
@pytest.mark.parametrize("disposition", list(RecoveryDisposition))
def test_invalid_recovery_state_refuses_without_any_write(tmp_path, kind, row, disposition):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        terminal = row.startswith("terminal_")
        reach(registrar, original, approval, None if terminal else "receipt_verified")
        if row.endswith("third_config"):
            fixture.config_path.write_text('{"unreviewed_host_edit":true}\n')
        elif row.endswith("third_receipt"):
            set_image(store.receipt_path(), b'{"unreviewed_receipt":true}')
        elif row == "missing_journal":
            store.journal_path(original.operation_id).unlink()
        elif row == "invalid_journal":
            set_image(store.journal_path(original.operation_id), b'{}')
        elif row == "altered_journal":
            journal = json.loads(store.journal_path(original.operation_id).read_bytes())
            journal.update(action="unregister", unexpected="fixture")
            set_image(store.journal_path(original.operation_id), json.dumps(journal).encode())
        elif row == "terminal_corrupt":
            set_image(store.terminal_path(original.operation_id), b'{}')
        before = snapshot(fixture.root)
        with pytest.raises(RegistrarError) as caught:
            if terminal:
                registrar.recover(original, disposition, approval)
            else:
                registrar.prepare_recovery(original, disposition)
        assert caught.value.code is ReasonCode.RECOVERY_CONFLICT
        assert snapshot(fixture.root) == before


@pytest.mark.parametrize("kind", ["register", "unregister", "update", "rollback"])
@pytest.mark.parametrize("disposition", list(RecoveryDisposition))
def test_c0_r1_is_not_a_recoverable_pair(tmp_path, kind, disposition):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        reach(registrar, original, approval, "receipt_verified")
        set_image(fixture.config_path, images[0])
        before = snapshot(fixture.root)
        with pytest.raises(RegistrarError) as caught:
            registrar.prepare_recovery(original, disposition)
        assert caught.value.code is ReasonCode.RECOVERY_CONFLICT
        assert snapshot(fixture.root) == before


@pytest.mark.parametrize("kind", ["register", "adopt", "update"])
def test_cancelled_marker_blocks_completion_and_replays_cancellation(tmp_path, kind):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        reach(registrar, original, approval, "journal_prepared")
        cancellation = registrar.prepare_recovery(original, RecoveryDisposition.CANCEL)
        result = registrar.recover(cancellation, RecoveryDisposition.CANCEL, fixture_approval(cancellation))
        assert result.outcome is Outcome.CANCELLED
        assert_pair(fixture, store, images, final=False)
        before = snapshot(fixture.root)
        for action in (lambda: registrar.apply(original, approval),
                       lambda: registrar.recover(original, RecoveryDisposition.COMPLETE, approval)):
            with pytest.raises(RegistrarError):
                action()
            assert snapshot(fixture.root) == before
        replay = registrar.recover(original, RecoveryDisposition.CANCEL, approval)
        assert replay.outcome is Outcome.CANCELLED
        assert replay.config_changed is False and replay.state_changed is False
        assert snapshot(fixture.root) == before


@pytest.mark.parametrize("disposition", list(RecoveryDisposition))
def test_zero_change_preparation_can_only_complete_or_cancel_explicitly(tmp_path, disposition):
    with scenario(tmp_path, "zero") as (registrar, fixture, original, approval, store, images):
        assert images[0] == images[1] and images[2] == images[3]
        if disposition is RecoveryDisposition.COMPLETE:
            result = registrar.apply(original, approval)
            assert result.outcome is Outcome.NO_CHANGE
        else:
            cancel = registrar.prepare_cancel(original)
            result = registrar.apply(cancel, fixture_approval(cancel))
            assert result.outcome is Outcome.CANCELLED
        assert result.config_changed is False and result.state_changed is True
        assert_pair(fixture, store, images, final=False)


@pytest.mark.parametrize("kind", ["register", "update"])
@pytest.mark.parametrize("original_phase", ["config_replaced", "receipt_verified"])
@pytest.mark.parametrize("inverse_phase", ["journal_prepared", "config_replaced", "receipt_verified"])
def test_interrupted_inverse_recovers_and_blocks_original_forward_replay(tmp_path, kind, original_phase, inverse_phase):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        reach(registrar, original, approval, original_phase)
        inverse = registrar.prepare(registrar.rollback(operation_ref(original, pending=True), context=fixture.context))
        inverse_approval = fixture_approval(inverse)
        reach(registrar, inverse, inverse_approval, inverse_phase)
        before = snapshot(fixture.root)
        with pytest.raises(RegistrarError):
            registrar.apply(original, approval)
        with pytest.raises(RegistrarError):
            registrar.prepare_recovery(original, RecoveryDisposition.COMPLETE)
        assert snapshot(fixture.root) == before
        recovery = registrar.prepare_recovery(inverse, RecoveryDisposition.COMPLETE)
        result = registrar.recover(recovery, RecoveryDisposition.COMPLETE, fixture_approval(recovery))
        assert result.outcome is Outcome.RECOVERED
        assert_pair(fixture, store, images, final=False)
        before = snapshot(fixture.root)
        with pytest.raises(RegistrarError):
            registrar.apply(original, approval)
        assert snapshot(fixture.root) == before


@pytest.mark.parametrize("kind", ["register", "update"])
def test_committed_rollback_restores_exact_config_and_previous_receipt(tmp_path, kind):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        registrar.apply(original, approval)
        inverse = registrar.prepare(registrar.rollback(operation_ref(original), context=fixture.context))
        result = registrar.apply(inverse, fixture_approval(inverse))
        assert result.outcome is Outcome.ROLLED_BACK
        assert result.config_changed is (images[0] != images[1]) and result.state_changed is True
        assert_pair(fixture, store, images, final=False)


def test_corrupt_committed_terminal_cannot_authorize_rollback(tmp_path):
    with scenario(tmp_path, "register") as (registrar, fixture, original, approval, store, images):
        registrar.apply(original, approval)
        set_image(store.terminal_path(original.operation_id), b'{}')
        before = snapshot(fixture.root)
        with pytest.raises(RegistrarError):
            registrar.prepare(registrar.rollback(operation_ref(original), context=fixture.context))
        assert snapshot(fixture.root) == before


@pytest.mark.parametrize("kind", ["register", "update"])
def test_unapplied_cancel_discards_unused_private_staging_after_durable_receipt(tmp_path, kind):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        cancel = registrar.prepare_cancel(original)
        result = registrar.apply(cancel, fixture_approval(cancel))
        assert result.outcome is Outcome.CANCELLED
        assert_pair(fixture, store, images, final=False)
        assert not store.prepared_path(original.record_id).exists()
        staged_output = base64.b64encode(images[1])
        # Completed cancellation must not leave the unused planned output copied
        # into a journal or secondary preparation under another filename.
        assert all(staged_output not in p.read_bytes() for p in fixture.state_directory.iterdir() if p.is_file())
        terminal = json.loads(store.terminal_path(original.operation_id).read_bytes())
        assert terminal["result"]["outcome"] == "cancelled"
        assert "/opt/fixture/matrix" not in json.dumps(terminal)



def test_rollback_cannot_transfer_original_source_ownership(tmp_path):
    with scenario(tmp_path, "register") as (registrar, fixture, original, approval, store, images):
        registrar.apply(original, approval)
        foreign = replace(fixture.context, source_owner="Other/owner")
        before = snapshot(fixture.root)
        with pytest.raises(RegistrarError):
            registrar.prepare(registrar.rollback(operation_ref(original), context=foreign))
        assert snapshot(fixture.root) == before


STATE_REFUSALS = {ReasonCode.STATE_INVALID, ReasonCode.JOURNAL_INVALID,
                  ReasonCode.RECOVERY_CONFLICT, ReasonCode.PREPARED_RECORD_REQUIRED, ReasonCode.PREIMAGE_CHANGED}


def assert_bounded_state_refusal(call, fixture, *, expected_code=None):
    from kp_mcp_bootstrap.registrars import Inspection, Preview, Result

    before = snapshot(fixture.root)
    try:
        result = call()
    except RegistrarError as error:
        assert error.code in STATE_REFUSALS
        if expected_code is not None:
            assert error.code is expected_code
    else:
        if isinstance(result, Preview):
            assert not result.ready and set(result.conflicts) & STATE_REFUSALS
        elif isinstance(result, Inspection):
            assert set(result.reason_codes) & STATE_REFUSALS
            assert result.observations.registered.status.value != "pass"
        elif isinstance(result, Result):
            assert result.outcome in {Outcome.FAILED, Outcome.RECOVERY_REQUIRED}
            assert set(result.reason_codes) & STATE_REFUSALS
            if expected_code is not None:
                assert result.reason_codes[0] is expected_code
            assert not result.config_changed and not result.state_changed
        else:
            pytest.fail(f"Invalid durable authority accepted by {type(result).__name__}")
    assert snapshot(fixture.root) == before


@pytest.mark.parametrize("kind", ["register", "adopt"])
@pytest.mark.parametrize("record_kind", ["prepared", "journal", "terminal", "receipt"])
@pytest.mark.parametrize("entrypoint", ["apply", "recover_complete", "recover_cancel", "prepare_complete",
                                        "prepare_cancel_recovery", "cancel", "rollback_committed",
                                        "rollback_pending", "inspect"])
def test_corrupt_durable_authority_refuses_across_verbs_and_reference_kinds(tmp_path, kind, record_kind, entrypoint):
    from kp_mcp_bootstrap.registrars import OperationRefKind

    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        registrar.apply(original, approval)
        reference = operation_ref(original)
        paths = {"prepared": store.prepared_path(original.record_id),
                 "journal": store.journal_path(original.operation_id),
                 "terminal": store.terminal_path(original.operation_id), "receipt": store.receipt_path()}
        set_image(paths[record_kind], b'{}')
        actions = {
            "apply": lambda: registrar.apply(original, approval),
            "recover_complete": lambda: registrar.recover(original, RecoveryDisposition.COMPLETE, approval),
            "recover_cancel": lambda: registrar.recover(original, RecoveryDisposition.CANCEL, approval),
            "prepare_complete": lambda: registrar.prepare_recovery(original, RecoveryDisposition.COMPLETE),
            "prepare_cancel_recovery": lambda: registrar.prepare_recovery(original, RecoveryDisposition.CANCEL),
            "cancel": lambda: registrar.prepare_cancel(original),
            "rollback_committed": lambda: registrar.rollback(reference, context=fixture.context),
            "rollback_pending": lambda: registrar.rollback(replace(reference, kind=OperationRefKind.PENDING_JOURNAL), context=fixture.context),
            "inspect": lambda: registrar.inspect_registration(fixture.config_path, context=fixture.context),
        }
        recovery_call = entrypoint in {"recover_complete", "recover_cancel", "prepare_complete", "prepare_cancel_recovery"}
        expected_code = ReasonCode.RECOVERY_CONFLICT if recovery_call and record_kind != "prepared" else None
        assert_bounded_state_refusal(actions[entrypoint], fixture, expected_code=expected_code)


@pytest.mark.parametrize("kind", ["register", "adopt", "update"])
@pytest.mark.parametrize("phase", ["journal_prepared", "config_replaced", "receipt_verified"])
@pytest.mark.parametrize("entrypoint", ["preview", "preview_unregister", "inspect", "prepare", "apply"])
def test_unresolved_target_blocks_fresh_operations_even_if_prepared_before_interruption(tmp_path, kind, phase, entrypoint):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        fresh_preview = registrar.preview(fixture.config_path, original._definition, context=fixture.context)
        fresh_prepared = registrar.prepare(fresh_preview)
        fresh_approval = fixture_approval(fresh_prepared)
        reach(registrar, original, approval, phase)
        actions = {
            "preview": lambda: registrar.preview(fixture.config_path, original._definition, context=fixture.context),
            "preview_unregister": lambda: registrar.preview_unregister(fixture.config_path, context=fixture.context),
            "inspect": lambda: registrar.inspect_registration(fixture.config_path, context=fixture.context),
            "prepare": lambda: registrar.prepare(fresh_preview),
            "apply": lambda: registrar.apply(fresh_prepared, fresh_approval),
        }
        assert_bounded_state_refusal(actions[entrypoint], fixture)


@pytest.mark.parametrize("kind", ["register", "adopt", "update"])
@pytest.mark.parametrize("phase", ["journal_prepared", "config_replaced", "receipt_verified"])
@pytest.mark.parametrize("entrypoint", ["apply", "prepare_complete", "recover_complete"])
def test_started_cancellation_blocks_original_forward_entrypoints(tmp_path, kind, phase, entrypoint):
    with scenario(tmp_path, kind) as (registrar, fixture, original, approval, store, images):
        cancellation = registrar.prepare_cancel(original)
        reach(registrar, cancellation, fixture_approval(cancellation), phase)
        actions = {
            "apply": lambda: registrar.apply(original, approval),
            "prepare_complete": lambda: registrar.prepare_recovery(original, RecoveryDisposition.COMPLETE),
            "recover_complete": lambda: registrar.recover(original, RecoveryDisposition.COMPLETE, approval),
        }
        assert_bounded_state_refusal(actions[entrypoint], fixture)


SECONDARY_KINDS = ("rollback_committed", "rollback_pending", "recover", "cancel_pending", "cancel_unstarted")
SECONDARY_TAMPERING = [
    (kind, corruption)
    for kind in SECONDARY_KINDS
    for corruption in ("prepared_corrupt", "prepared_missing", "journal_corrupt", "terminal_corrupt")
] + [
    (kind, corruption)
    for kind in SECONDARY_KINDS if kind != "cancel_unstarted"
    for corruption in ("journal_missing", "journal_phase_changed")
] + [("rollback_committed", "terminal_missing")]


@pytest.mark.parametrize("kind,corruption", SECONDARY_TAMPERING)
def test_secondary_apply_revalidates_exact_original_authority_before_any_write(tmp_path, kind, corruption):
    with scenario(tmp_path, "register") as (registrar, fixture, original, approval, store, images):
        if kind == "rollback_committed":
            registrar.apply(original, approval)
        elif kind == "rollback_pending":
            reach(registrar, original, approval, "receipt_verified")
        elif kind in {"recover", "cancel_pending"}:
            reach(registrar, original, approval, "journal_prepared")
        if kind.startswith("rollback"):
            secondary = registrar.prepare(registrar.rollback(operation_ref(original, pending=kind.endswith("pending")), context=fixture.context))
        elif kind == "recover":
            secondary = registrar.prepare_recovery(original, RecoveryDisposition.COMPLETE)
        elif kind == "cancel_pending":
            secondary = registrar.prepare_recovery(original, RecoveryDisposition.CANCEL)
        else:
            secondary = registrar.prepare_cancel(original)
        secondary_approval = fixture_approval(secondary)
        record_kind, mutation = corruption.split("_", 1)
        path = {"prepared": store.prepared_path(original.record_id),
                "journal": store.journal_path(original.operation_id),
                "terminal": store.terminal_path(original.operation_id)}[record_kind]
        if mutation == "missing":
            path.unlink()
        elif mutation == "phase_changed":
            journal = json.loads(path.read_bytes())
            journal["phase"] = "verified" if journal["phase"] != "verified" else "config_replaced"
            set_image(path, json.dumps(journal).encode())
        else:
            set_image(path, b'{}')
        assert_bounded_state_refusal(lambda: registrar.apply(secondary, secondary_approval), fixture)


@pytest.mark.parametrize("action,phase", [
    ("refuse_expired_complete", "journal_prepared"), ("complete", "config_replaced"),
    ("complete", "receipt_verified"), ("cancel_pending", "journal_prepared"),
    ("cancel_unstarted", None), ("refuse_expired_zero", "journal_prepared"),
])
def test_expired_original_can_only_transition_using_fresh_fixture_authority(tmp_path, monkeypatch, action, phase):
    from datetime import timedelta
    from kp_mcp_bootstrap.registrars import renew_fixture_context
    from kp_mcp_bootstrap.registrars import contracts, transactions, writer_window

    with scenario(tmp_path, "zero" if action == "refuse_expired_zero" else "register") as (registrar, fixture, original, approval, store, images):
        if phase is not None:
            reach(registrar, original, approval, phase)
        later = fixture.context.writer_window.expires_at + timedelta(seconds=1)
        monkeypatch.setattr(contracts, "utc_now", lambda: later)
        monkeypatch.setattr(transactions, "utc_now", lambda: later)
        monkeypatch.setattr(writer_window, "utc_now", lambda: later)
        before = snapshot(fixture.root)
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(original, approval)
        assert caught.value.code in {ReasonCode.CONCURRENCY_UNQUALIFIED, ReasonCode.STALE_PREVIEW}
        assert snapshot(fixture.root) == before

        fresh = renew_fixture_context(fixture.context)
        assert fresh.config_path == fixture.context.config_path
        assert fresh.state_directory == fixture.context.state_directory
        assert fresh.writer_window.digest != fixture.context.writer_window.digest
        if action in {"refuse_expired_complete", "refuse_expired_zero"}:
            # ADR413 requires original forward authority at C0/R0/P. A new
            # window is not an extension of the original prepared approval.
            before = snapshot(fixture.root)
            with pytest.raises(RegistrarError) as caught:
                registrar.prepare_recovery(original, RecoveryDisposition.COMPLETE, context=fresh)
            assert caught.value.code in {ReasonCode.APPROVAL_INVALID, ReasonCode.CONCURRENCY_UNQUALIFIED, ReasonCode.STALE_PREVIEW}
            assert snapshot(fixture.root) == before
        else:
            if action == "cancel_unstarted":
                secondary = registrar.prepare_cancel(original, context=fresh)
            else:
                disposition = RecoveryDisposition.COMPLETE if action == "complete" else RecoveryDisposition.CANCEL
                secondary = registrar.prepare_recovery(original, disposition, context=fresh)
            result = registrar.apply(secondary, fixture_approval(secondary))
            assert result.outcome is (Outcome.RECOVERED if action == "complete" else Outcome.CANCELLED)
        assert_pair(fixture, store, images, final=action == "complete")
        before = snapshot(fixture.root)
        with pytest.raises(RegistrarError):
            registrar.apply(original, approval)
        assert snapshot(fixture.root) == before
    assert not fixture.root.exists()
    with pytest.raises(RegistrarError):
        renew_fixture_context(fresh)
