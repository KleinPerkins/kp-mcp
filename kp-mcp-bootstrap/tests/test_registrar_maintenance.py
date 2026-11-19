"""Synthetic maintenance outcomes. No test profile is shipped as live authority."""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from kp_mcp_bootstrap.registrars import (
    Action, Approval, CursorRegistrar, KnownWriterEvidence, MaintenanceEvidence,
    Outcome, ReasonCode, RecoveryDisposition, RegistrarError,
    RegistrationDefinition, SourceIdentity, fixture_context,
)
from kp_mcp_bootstrap.registrars import maintenance
from kp_mcp_bootstrap.registrars.contracts import (
    ApprovalAudience, canonical_json_bytes, context_from_record, digest_value, utc_now,
)
from kp_mcp_bootstrap.registrars.durable_validation import (
    _bind_original_authority, _image_digest, _load_record_by_id,
)
from kp_mcp_bootstrap.registrars.state import StateStore

REVISION = "c" * 40


class SyntheticValidator:
    validator_id = maintenance.VALIDATOR_ID
    issuer_source_revision = REVISION

    def __init__(self):
        self.status = {}
        self.approvals = {}
        self.eligible_material = {None}
        self.requests = []
        self.reject_phase = None

    def validate(self, request):
        self.requests.append(request)
        if (self.status.get(request.context.maintenance_evidence.maintenance_id) != "acquired"
            or request.phase == self.reject_phase
            or any(b not in self.eligible_material for b in request.durable_material)):
            raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED)
        if request.approval is not None and self.approvals.get(request.operation_id) != request.approval:
            raise RegistrarError(ReasonCode.APPROVAL_INVALID)

    def approve(self, prepared):
        window = prepared._context.writer_window
        approval = Approval(prepared.audience, prepared.operation_id, prepared.action_digest,
                            prepared.payload_digest, maintenance.APPROVAL_ISSUER,
                            window.acquisition_reference, utc_now(), prepared.expires_at)
        self.approvals[prepared.operation_id] = approval
        return approval

    def classify(self, preview):
        private = preview._private
        self.eligible_material.update((private.config_preimage, private.config_postimage,
                                       private.receipt_preimage, private.receipt_postimage))


def bind(context, validator, action=Action.REGISTER, *, predecessor=None, recovery_of=None):
    from kp_mcp_bootstrap.registrars.state import inspect_target
    now = utc_now()
    maintenance_id = str(uuid.uuid4())
    store = StateStore(context)
    evidence = MaintenanceEvidence(
        maintenance_id, REVISION, maintenance.ACCEPTED_CONTRACT_DIGEST,
        digest_value(ApprovalAudience(context.source_owner, context.connection_id, context.host,
                                     context.scope, inspect_target(context.config_path).target_id, action).to_record()),
        context.target_id, context.writer_window.state_target_id,
        _image_digest(context.config_path.read_bytes() if context.config_path.exists() else None),
        _image_digest(store.read_optional(store.receipt_path(inspect_target(context.config_path).target_id))),
        (KnownWriterEvidence("fixture-writer", "native-client", "inactive", "inactive",
                             "synthetic-observation", "a" * 64, now, "restore_prior"),),
        "b" * 64, maintenance_id, now, now + timedelta(minutes=9),
        "not_enrolled", "not_applicable", predecessor, recovery_of,
    )
    window = replace(context.writer_window, schema="kp-mcp/writer-window/v2",
                     mechanism="coordinated-maintenance", concurrency_claim="coordinated",
                     maintenance_evidence_digest=evidence.digest,
                     qualification_id=maintenance.QUALIFICATION_ID,
                     qualification_digest=maintenance.QUALIFICATION_DIGEST,
                     issuer_owner="KleinPerkins/dev", issuer_source_revision=REVISION,
                     acquisition_reference=maintenance_id, acquired_at=now, expires_at=evidence.expires_at,
                     release_method="dev-int014-explicit-handoff/v1")
    validator.status[maintenance_id] = "acquired"
    return replace(context, schema="kp-mcp/registration-context/v2", writer_window=window,
                   maintenance_evidence=evidence)


@contextmanager
def example(tmp_path, monkeypatch, *, qualify=True):
    if qualify:
        monkeypatch.setattr(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION}))
    validator = SyntheticValidator()
    registrar = CursorRegistrar(maintenance_validator=validator)
    definition = RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:maintenance-fixture", "d" * 40, "maintenance-fixture"),
        command="/opt/fixtures/maintenance", args=("mcp",),
    )
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        context = bind(fixture.context, validator)
        yield registrar, definition, context, validator


def prepared_example(registrar, definition, context, validator):
    preview = registrar.preview(context.config_path, definition, context=context)
    validator.classify(preview)
    return registrar.prepare(preview)


def test_maintenance_apply_reload_and_provenance(tmp_path, monkeypatch):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        approval = validator.approve(prepared)
        result = registrar.apply(prepared, approval)
        assert result.outcome is Outcome.APPLIED
        assert result.to_dict()["concurrency_claim"] == "coordinated"
        assert result.to_dict()["maintenance_evidence_digest"] == context.maintenance_evidence.digest
        assert context_from_record(json.loads(canonical_json_bytes(context.to_record()))) == context
        reloaded = CursorRegistrar(maintenance_validator=validator)
        restored = reloaded.load_prepared(prepared.record_id, context=context, definition=definition)
        assert reloaded.apply(restored, approval).outcome is Outcome.NO_CHANGE
        assert reloaded.inspect_registration(context.config_path, context=context)
        records = [json.loads(p.read_bytes()) for p in context.state_directory.glob("*.json")]
        for record in records:
            if record["schema"].endswith("/v2"):
                assert record["concurrency_claim"] == "coordinated"
                assert record["maintenance_evidence_digest"] == context.maintenance_evidence.digest
        phases = {r.phase for r in validator.requests}
        assert {"prepare_locked", "journal_prepared", "config_replace", "receipt_replace", "terminal_commit"} <= phases
        assert any(r.phase == "receipt_replace" and r.expected_config_digest == result.verified_postimage
                   for r in validator.requests)


@pytest.mark.parametrize("phase", ["prepare", "prepare_locked", "journal_prepared", "config_replace",
                                    "journal_config_replaced", "receipt_replace", "journal_verified",
                                    "journal_committed", "terminal_commit"])
def test_each_mutation_reobserves_and_refuses_restart(tmp_path, monkeypatch, phase):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        validator.reject_phase = phase
        if phase.startswith("prepare"):
            with pytest.raises(RegistrarError):
                prepared_example(registrar, definition, context, validator)
            assert not list(context.state_directory.glob("*.json"))
            assert not context.config_path.exists()
        else:
            prepared = prepared_example(registrar, definition, context, validator)
            if phase == "journal_prepared":
                with pytest.raises(RegistrarError):
                    registrar.apply(prepared, validator.approve(prepared))
                assert not list(context.state_directory.glob("journal-*.json"))
            else:
                result = registrar.apply(prepared, validator.approve(prepared))
                assert result.outcome is Outcome.RECOVERY_REQUIRED
                assert list(context.state_directory.glob("journal-*.json"))
                assert not list(context.state_directory.glob("terminal-*.json"))


@pytest.mark.parametrize("status", ["applied_pending_handoff", "recovery_required", "released", "release_failed", "cancelled"])
def test_nonacquired_lifecycle_never_writes(tmp_path, monkeypatch, status):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        approval = validator.approve(prepared)
        validator.status[context.maintenance_evidence.maintenance_id] = status
        before = {p: p.read_bytes() for p in context.state_directory.iterdir()}
        with pytest.raises(RegistrarError):
            registrar.apply(prepared, approval)
        assert {p: p.read_bytes() for p in context.state_directory.iterdir()} == before
        assert not context.config_path.exists()


def test_unqualified_production_revision_and_missing_runtime_refuse(tmp_path, monkeypatch):
    with example(tmp_path, monkeypatch, qualify=False) as (registrar, definition, context, validator):
        with pytest.raises(RegistrarError):
            prepared_example(registrar, definition, context, validator)
        assert not list(context.state_directory.glob("*.json"))
        monkeypatch.setattr(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION}))
        prepared = prepared_example(registrar, definition, context, validator)
        with pytest.raises(RegistrarError):
            CursorRegistrar().apply(prepared, validator.approve(prepared))
        validator.issuer_source_revision = "f" * 40
        with pytest.raises(RegistrarError):
            registrar.apply(prepared, validator.approve(prepared))


def test_unclassified_sibling_prevents_whole_file_persistence(tmp_path, monkeypatch):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        context.config_path.write_text('{"unrelated":"synthetic-private-material"}')
        context = bind(context, validator)
        preview = registrar.preview(context.config_path, definition, context=context)
        # Classification intentionally withheld for unrelated whole-file bytes.
        with pytest.raises(RegistrarError):
            registrar.prepare(preview)
        assert not list(context.state_directory.glob("*.json"))


@pytest.mark.parametrize("fault", ["journal_prepared", "config_replaced", "receipt_verified"])
def test_fresh_child_recovers_interrupted_operation(tmp_path, monkeypatch, fault):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        def interrupt(phase):
            if phase == fault:
                raise RuntimeError("synthetic interruption")
        monkeypatch.setattr(registrar, "_fault", interrupt)
        assert registrar.apply(prepared, validator.approve(prepared)).outcome is Outcome.RECOVERY_REQUIRED
        monkeypatch.setattr(registrar, "_fault", lambda _: None)
        store = StateStore(context)
        original = _load_record_by_id(store, prepared.operation_id)
        reference, _ = _bind_original_authority(store, original)
        validator.status[context.maintenance_evidence.maintenance_id] = "recovery_required"
        child = bind(context, validator, Action.RECOVER,
                     predecessor=context.maintenance_evidence.maintenance_id, recovery_of=reference)
        # The private original staging was already explicitly classified.
        recovery = registrar.prepare_recovery(prepared, RecoveryDisposition.COMPLETE, context=child)
        result = registrar.recover(recovery, RecoveryDisposition.COMPLETE, validator.approve(recovery))
        assert result.outcome is Outcome.RECOVERED
        assert result.to_dict()["maintenance_evidence_digest"] == child.maintenance_evidence.digest


@pytest.mark.parametrize("change", [{"unexpected": True}, {"concurrency_claim": "native_exclusion"},
                                    {"maintenance_evidence_digest": "f" * 64}])
def test_rehashed_v2_durable_tampering_refuses(tmp_path, monkeypatch, change):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        path = StateStore(context).prepared_path(prepared.record_id)
        record = json.loads(path.read_bytes())
        record.update(change)
        record.pop("payload_digest")
        record["payload_digest"] = digest_value(record)
        path.write_bytes(canonical_json_bytes(record))
        with pytest.raises(RegistrarError):
            registrar.apply(prepared, validator.approve(prepared))


@pytest.mark.parametrize("action", [Action.CANCEL, Action.ROLLBACK])
def test_child_cancel_or_exact_rollback_is_terminal(tmp_path, monkeypatch, action):
    from kp_mcp_bootstrap.registrars import operation_ref
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        if action is Action.ROLLBACK:
            assert registrar.apply(prepared, validator.approve(prepared)).outcome is Outcome.APPLIED
            reference = operation_ref(prepared, maintenance_validator=validator)
        store = StateStore(context)
        original = _load_record_by_id(store, prepared.operation_id)
        digest, _ = _bind_original_authority(store, original)
        child = bind(context, validator, action,
                     predecessor=context.maintenance_evidence.maintenance_id, recovery_of=digest)
        if action is Action.CANCEL:
            secondary = registrar.prepare_cancel(prepared, context=child)
        else:
            preview = registrar.rollback(reference, context=child)
            validator.classify(preview)
            secondary = registrar.prepare(preview)
        result = registrar.apply(secondary, validator.approve(secondary))
        assert result.outcome is (Outcome.CANCELLED if action is Action.CANCEL else Outcome.ROLLED_BACK)
        assert not context.config_path.exists()
        # Cancellation drops staged bytes; subsequent target admission must
        # still validate its bounded terminal proof and the child lineage.
        next_context = bind(context, validator)
        assert registrar.preview(context.config_path, definition, context=next_context).ready


def test_noncooperating_write_can_be_lost_after_last_check(tmp_path, monkeypatch):
    from kp_mcp_bootstrap.registrars import state
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        context.config_path.write_text('{"mcpServers":{}}')
        context = bind(context, validator)
        prepared = prepared_example(registrar, definition, context, validator)
        replace_file = state.os.replace
        def interleave(source, destination):
            if Path(destination) == context.config_path:
                # Deterministic interleaving at the real last replacement
                # boundary: coordination cannot prevent this external write.
                context.config_path.write_text('{"external_writer":"unobserved"}')
            return replace_file(source, destination)
        monkeypatch.setattr(state.os, "replace", interleave)
        result = registrar.apply(prepared, validator.approve(prepared))
        assert result.outcome is Outcome.APPLIED
        assert "external_writer" not in context.config_path.read_text()
        assert result.concurrency_claim == "coordinated"


def test_interrupted_inverse_recovers_with_grandchild_authority(tmp_path, monkeypatch):
    from kp_mcp_bootstrap.registrars import operation_ref
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        assert registrar.apply(prepared, validator.approve(prepared)).outcome is Outcome.APPLIED
        operation = operation_ref(prepared, maintenance_validator=validator)
        original = _load_record_by_id(StateStore(context), prepared.record_id)
        reference, _ = _bind_original_authority(StateStore(context), original)
        child = bind(context, validator, Action.ROLLBACK,
                     predecessor=context.maintenance_evidence.maintenance_id, recovery_of=reference)
        preview = registrar.rollback(operation, context=child)
        validator.classify(preview)
        inverse = registrar.prepare(preview)
        def interrupt(phase):
            if phase == "config_replaced":
                raise RuntimeError("interrupted inverse")
        monkeypatch.setattr(registrar, "_fault", interrupt)
        assert registrar.apply(inverse, validator.approve(inverse)).outcome is Outcome.RECOVERY_REQUIRED
        monkeypatch.setattr(registrar, "_fault", lambda _: None)
        validator.status[child.maintenance_evidence.maintenance_id] = "recovery_required"
        original = _load_record_by_id(StateStore(child), inverse.record_id)
        reference, _ = _bind_original_authority(StateStore(child), original)
        grandchild = bind(child, validator, Action.RECOVER,
                          predecessor=child.maintenance_evidence.maintenance_id, recovery_of=reference)
        recovered = registrar.prepare_recovery(inverse, RecoveryDisposition.COMPLETE, context=grandchild)
        assert registrar.recover(recovered, RecoveryDisposition.COMPLETE,
                                 validator.approve(recovered)).outcome is Outcome.RECOVERED
        assert not context.config_path.exists()
        next_context = bind(context, validator)
        assert registrar.preview(context.config_path, definition, context=next_context).ready


@pytest.mark.parametrize("phase", ["original_journal", "original_terminal", "cancel_staging_remove"])
def test_child_terminalization_has_fresh_authority_checks(tmp_path, monkeypatch, phase):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        original = _load_record_by_id(StateStore(context), prepared.record_id)
        reference, _ = _bind_original_authority(StateStore(context), original)
        child = bind(context, validator, Action.CANCEL,
                     predecessor=context.maintenance_evidence.maintenance_id, recovery_of=reference)
        secondary = registrar.prepare_cancel(prepared, context=child)
        validator.reject_phase = phase
        result = registrar.apply(secondary, validator.approve(secondary))
        assert result.outcome is Outcome.RECOVERY_REQUIRED
        assert not context.config_path.exists()
        assert StateStore(context).prepared_path(prepared.record_id).exists()


@pytest.mark.parametrize("action,phase", [(Action.CANCEL, "original_terminal"),
                                         (Action.CANCEL, "cancel_staging_remove"),
                                         (Action.CANCEL, "original_journal"),
                                         (Action.ROLLBACK, "original_journal"),
                                         (Action.ROLLBACK, "original_terminal")])
def test_interrupted_predecessor_terminalization_is_recoverable(tmp_path, monkeypatch, action, phase):
    from kp_mcp_bootstrap.registrars import operation_ref
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        if action is Action.ROLLBACK:
            registrar.apply(prepared, validator.approve(prepared))
            operation = operation_ref(prepared, maintenance_validator=validator)
        store = StateStore(context)
        original = _load_record_by_id(store, prepared.record_id)
        reference, _ = _bind_original_authority(store, original)
        child = bind(context, validator, action,
                     predecessor=context.maintenance_evidence.maintenance_id, recovery_of=reference)
        if action is Action.CANCEL:
            secondary = registrar.prepare_cancel(prepared, context=child)
        else:
            preview = registrar.rollback(operation, context=child)
            validator.classify(preview)
            secondary = registrar.prepare(preview)
        validator.reject_phase = phase
        assert registrar.apply(secondary, validator.approve(secondary)).outcome is Outcome.RECOVERY_REQUIRED
        validator.reject_phase = None
        original = _load_record_by_id(store, secondary.record_id)
        reference, _ = _bind_original_authority(store, original)
        grandchild = bind(child, validator, Action.RECOVER,
                          predecessor=child.maintenance_evidence.maintenance_id, recovery_of=reference)
        recovered = registrar.prepare_recovery(secondary, RecoveryDisposition.COMPLETE, context=grandchild)
        assert registrar.recover(recovered, RecoveryDisposition.COMPLETE,
                                 validator.approve(recovered)).outcome is Outcome.RECOVERED
        assert registrar.preview(context.config_path, definition, context=bind(context, validator)).ready
        if action is Action.CANCEL:
            assert not store.prepared_path(prepared.record_id).exists()


def test_expiry_after_journal_stops_config_write(tmp_path, monkeypatch):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        def expire(phase):
            if phase == "journal_prepared":
                monkeypatch.setattr(maintenance, "utc_now", lambda: context.writer_window.expires_at + timedelta(seconds=1))
        monkeypatch.setattr(registrar, "_fault", expire)
        result = registrar.apply(prepared, validator.approve(prepared))
        assert result.outcome is Outcome.RECOVERY_REQUIRED
        assert result.reason_codes == (ReasonCode.CONCURRENCY_UNQUALIFIED,)
        assert not context.config_path.exists()


def test_fixture_issuer_cannot_authorize_maintenance(tmp_path, monkeypatch):
    from kp_mcp_bootstrap.registrars import fixture_approval
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        with pytest.raises(RegistrarError):
            fixture_approval(prepared)
        approval = replace(validator.approve(prepared), issuer_authority="kp-mcp/fixture-isolation/v1")
        validator.approvals[prepared.operation_id] = approval
        with pytest.raises(RegistrarError):
            registrar.apply(prepared, approval)
        assert not context.config_path.exists()


@pytest.mark.parametrize("kind", ["journal", "terminal"])
def test_mixed_mode_durable_history_is_rejected(tmp_path, monkeypatch, kind):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        approval = validator.approve(prepared)
        registrar.apply(prepared, approval)
        store = StateStore(context)
        path = store.journal_path(prepared.record_id) if kind == "journal" else store.terminal_path(prepared.record_id)
        record = json.loads(path.read_bytes())
        record["schema"] = record["schema"][:-1] + "1"
        for key in ("concurrency_claim", "writer_window_digest", "maintenance_evidence_digest"):
            record.pop(key)
        if kind == "terminal":
            record.pop("terminal_digest")
            record["terminal_digest"] = digest_value(record)
        path.write_bytes(canonical_json_bytes(record))
        with pytest.raises(RegistrarError):
            registrar.apply(prepared, approval)


def test_unknown_fields_and_cross_version_context_rejected(tmp_path, monkeypatch):
    with example(tmp_path, monkeypatch) as (_, _, context, _):
        record = json.loads(canonical_json_bytes(context.to_record()))
        record["maintenance_evidence"]["validated"] = True
        with pytest.raises((ValueError, RegistrarError)):
            context_from_record(record)
        with pytest.raises(RegistrarError):
            replace(context, schema="kp-mcp/registration-context/v1")
        with pytest.raises(RegistrarError):
            replace(context.writer_window, schema="kp-mcp/writer-window/v1")


def test_fresh_process_has_no_inherited_runtime_authority(tmp_path, monkeypatch):
    import subprocess
    import sys
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        script = """
import sys
from kp_mcp_bootstrap.registrars import CursorRegistrar, RegistrarError
from kp_mcp_bootstrap.registrars.contracts import context_from_record, strict_json_loads
context = context_from_record(strict_json_loads(sys.stdin.buffer.read()))
try:
    CursorRegistrar().load_prepared(sys.argv[1], context=context, definition=None)
except RegistrarError as error:
    assert error.code.value == 'concurrency_unqualified'
else:
    raise AssertionError('persisted bytes supplied runtime authority')
"""
        result = subprocess.run([sys.executable, "-c", script, prepared.record_id],
                                input=canonical_json_bytes(context.to_record()), capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        assert not context.config_path.exists()


def test_v2_links_v1_ownership_but_cannot_replay_v1_operation(tmp_path, monkeypatch):
    from kp_mcp_bootstrap.registrars import fixture_approval, operation_ref
    monkeypatch.setattr(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION}))
    validator = SyntheticValidator()
    registrar = CursorRegistrar(maintenance_validator=validator)
    definition = RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:prior-owner", "d" * 40, "prior-owner"),
        command="/opt/fixtures/prior-owner", args=("mcp",),
    )
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        old = registrar.prepare(registrar.preview(fixture.config_path, definition, context=fixture.context))
        assert registrar.apply(old, fixture_approval(old)).outcome is Outcome.APPLIED
        ref = operation_ref(old)
        context = bind(fixture.context, validator, Action.ROLLBACK)
        with pytest.raises(RegistrarError):
            registrar.rollback(ref, context=context)
        desired = RegistrationDefinition.stdio(definition.identity, command="/opt/fixtures/prior-owner",
                                               args=("mcp", "--offline-fixture"))
        context = bind(replace(fixture.context, definition_digest=desired.digest), validator)
        prepared = prepared_example(registrar, desired, context, validator)
        assert registrar.apply(prepared, validator.approve(prepared)).outcome is Outcome.APPLIED
        assert registrar.inspect_registration(fixture.config_path, context=context)


@pytest.mark.parametrize("kit", ["google", "snow", "widget"])
def test_kit_batch_propagates_explicit_validator(tmp_path, monkeypatch, kit):
    from contextlib import ExitStack
    from google_kit import bootstrap as google
    from snow_kit import bootstrap as snow
    from widget_kit import bootstrap as widget
    module = {"google": google, "snow": snow, "widget": widget}[kit]
    monkeypatch.setattr(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION}))
    validator = SyntheticValidator()
    registrars = module.registrars(maintenance_validator=validator)
    kwargs = {"binary_path": "/opt/fixtures/kit"}
    if kit == "snow":
        kwargs["config_path"] = tmp_path / "profile.env"
    definition = module.registration_definition("d" * 40, **kwargs)
    contexts, prepared, approvals, paths = {}, {}, {}, {}
    with ExitStack() as stack:
        for host, registrar in registrars.items():
            fixture = stack.enter_context(fixture_context(registrar, definition, fixture_root=tmp_path))
            contexts[host] = bind(fixture.context, validator)
            paths[host + "_path"] = fixture.config_path
            prepared[host] = prepared_example(registrar, definition, contexts[host], validator)
            approvals[host] = validator.approve(prepared[host])
        with pytest.raises(RegistrarError):
            module.register_all(**paths, **kwargs, contexts=contexts, prepared=prepared, approvals=approvals)
        assert not any(path.exists() for path in paths.values())
        results = module.register_all(**paths, **kwargs, contexts=contexts, prepared=prepared,
                                      approvals=approvals, maintenance_validator=validator)
        assert all(result.outcome is Outcome.APPLIED for result in results.values())


@pytest.mark.parametrize("change", [{"config_changed": False}, {"state_changed": False},
                                    {"owned_leaf_actions": ()}, {"preserved_paths": ("/invented",)},
                                    {"source_revision": "e" * 40}])
def test_rehashed_preview_semantics_refused_before_persistence(tmp_path, monkeypatch, change):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        preview = registrar.preview(context.config_path, definition, context=context)
        forged = replace(preview, **change)
        forged = replace(forged, preview_digest=digest_value(forged.digest_payload()))
        validator.classify(forged)
        with pytest.raises(RegistrarError):
            registrar.prepare(forged)
        assert not list(context.state_directory.glob("*.json"))
        assert not context.config_path.exists()


def test_unregister_remains_a_valid_root_operation(tmp_path, monkeypatch):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        assert registrar.apply(prepared, validator.approve(prepared)).outcome is Outcome.APPLIED
        context = bind(context, validator, Action.UNREGISTER)
        preview = registrar.preview_unregister(context.config_path, context=context)
        validator.classify(preview)
        prepared = registrar.prepare(preview)
        assert registrar.apply(prepared, validator.approve(prepared)).outcome is Outcome.APPLIED
        assert registrar.preview(context.config_path, definition, context=bind(context, validator)).ready


@pytest.mark.parametrize("change", [{"source_revision": "e" * 40}, {"build": "source-v1"}])
def test_rollback_rejects_changed_historical_identity(tmp_path, monkeypatch, change):
    from kp_mcp_bootstrap.registrars import operation_ref
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        registrar.apply(prepared, validator.approve(prepared))
        operation = operation_ref(prepared, maintenance_validator=validator)
        store = StateStore(context)
        reference, _ = _bind_original_authority(store, _load_record_by_id(store, prepared.record_id))
        child = bind(replace(context, **change), validator, Action.ROLLBACK,
                     predecessor=context.maintenance_evidence.maintenance_id, recovery_of=reference)
        before = {p: p.read_bytes() for p in context.state_directory.glob("*.json")}
        with pytest.raises(RegistrarError):
            registrar.rollback(operation, context=child)
        assert before == {p: p.read_bytes() for p in context.state_directory.glob("*.json")}
        assert registrar.inspect_registration(context.config_path, context=context)


@pytest.mark.parametrize("retarget", [False, True])
def test_stable_leaf_symlink_and_retarget_refusal(tmp_path, monkeypatch, retarget):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        target = context.config_path.with_name("real-config.json")
        target.write_text("{}")
        context.config_path.symlink_to(target.name)
        context = bind(context, validator)
        prepared = prepared_example(registrar, definition, context, validator)
        approval = validator.approve(prepared)
        if retarget:
            other = target.with_name("other-config.json")
            other.write_text("{}")
            context.config_path.unlink()
            context.config_path.symlink_to(other.name)
            with pytest.raises(RegistrarError):
                registrar.apply(prepared, approval)
            assert target.read_text() == other.read_text() == "{}"
        else:
            assert registrar.apply(prepared, approval).outcome is Outcome.APPLIED
            assert context.config_path.is_symlink()
            assert registrar.inspect_registration(context.config_path, context=context)


@pytest.mark.parametrize("action,with_original", [(Action.RECOVER, False), (Action.REGISTER, True)])
def test_invalid_root_secondary_matrix_refuses(tmp_path, monkeypatch, action, with_original):
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        context = bind(context, validator, action, predecessor=str(uuid.uuid4()) if with_original else None,
                       recovery_of="f" * 64 if with_original else None)
        preview = registrar.preview(context.config_path, definition, context=context)
        private = replace(preview._private,
                          original_operation_id=str(uuid.uuid4()) if with_original else None,
                          definition=definition if with_original else None)
        forged = replace(preview, action=action, _private=private,
                         private_recovery_reference="f" * 64 if with_original else None)
        forged = replace(forged, preview_digest=digest_value(forged.digest_payload()))
        validator.classify(forged)
        with pytest.raises(RegistrarError):
            registrar.prepare(forged)
        assert not list(context.state_directory.glob("*.json"))


@pytest.mark.parametrize("image", ["config_postimage", "receipt_postimage"])
@pytest.mark.parametrize("durable", [False, True])
def test_rehashed_arbitrary_postimages_are_not_source_projection(tmp_path, monkeypatch, image, durable):
    import base64
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        preview = registrar.preview(context.config_path, definition, context=context)
        forged_bytes = b'{"unrelated":"forged"}'
        preview_key = {"config_postimage": "desired_config", "receipt_postimage": "desired_receipt"}[image]
        if durable:
            validator.classify(preview)
            prepared = registrar.prepare(preview)
            path = StateStore(context).prepared_path(prepared.record_id)
            record = json.loads(path.read_bytes())
            record[image] = base64.b64encode(forged_bytes).decode("ascii")
            record["preview"][preview_key] = _image_digest(forged_bytes)
            record["preview"].pop("preview_digest")
            record["preview"]["preview_digest"] = digest_value(record["preview"])
            record.pop("payload_digest")
            record["payload_digest"] = digest_value(record)
            path.write_bytes(canonical_json_bytes(record))
            with pytest.raises(RegistrarError):
                registrar.load_prepared(prepared.record_id, context=context, definition=definition)
        else:
            forged = replace(preview, _private=replace(preview._private, **{image: forged_bytes}),
                             **{preview_key: _image_digest(forged_bytes)})
            forged = replace(forged, preview_digest=digest_value(forged.digest_payload()))
            validator.classify(forged)
            with pytest.raises(RegistrarError):
                registrar.prepare(forged)
            assert not list(context.state_directory.glob("*.json"))
        assert not context.config_path.exists()


def test_v1_prepared_record_cannot_embed_v2_preview(tmp_path):
    registrar = CursorRegistrar()
    definition = RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:strict-fixture", "d" * 40, "strict-fixture"),
        command="/opt/fixtures/strict", args=("mcp",),
    )
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(registrar.preview(fixture.config_path, definition, context=fixture.context))
        store = StateStore(fixture.context)
        path = store.prepared_path(prepared.record_id)
        record = json.loads(path.read_bytes())
        record["preview"]["schema"] = "kp-mcp/registrar-preview/v2"
        record["preview"].pop("preview_digest")
        record["preview"]["preview_digest"] = digest_value(record["preview"])
        record.pop("payload_digest")
        record["payload_digest"] = digest_value(record)
        path.write_bytes(canonical_json_bytes(record))
        with pytest.raises(RegistrarError):
            _load_record_by_id(store, prepared.record_id)
        assert not fixture.config_path.exists()


@pytest.mark.parametrize("host", ["cursor", "codex", "claude"])
def test_equal_adoption_preserves_entire_client_file(tmp_path, monkeypatch, host):
    from kp_mcp_bootstrap.registrars import ClaudeRegistrar, CodexRegistrar, MigrationEvidence
    from kp_mcp_bootstrap.registrars.ownership import set_leaf, semantic_digest
    monkeypatch.setattr(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION}))
    validator = SyntheticValidator()
    registrar = {"cursor": CursorRegistrar, "codex": CodexRegistrar, "claude": ClaudeRegistrar}[host](maintenance_validator=validator)
    definition = RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:adoption", "d" * 40, "adoption"),
        command="/opt/fixtures/adoption", args=("mcp",),
    )
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        source, auth, _ = registrar._native_projection(definition, fixture.context)
        entry = {"custom_setting": "keep"}
        for pointer, value in {**source, **auth}.items():
            set_leaf(entry, pointer, value)
        data = registrar._empty_data()
        data["unrelated_setting"] = "keep"
        registrar._set_entry(data, entry, definition.native_name)
        fixture.config_path.write_bytes(registrar._serialize_data(data))
        before = fixture.config_path.read_bytes()
        context = bind(fixture.context, validator, Action.ADOPT)
        evidence = MigrationEvidence(
            evidence_id="synthetic-maintenance-handoff", source_owner=definition.source_owner,
            connection_id=definition.connection_id, source_revision=definition.source_revision,
            host=context.host, scope=context.scope, native_name=definition.native_name,
            target_id=context.target_id, whole_file_digest=_image_digest(before),
            owned_leaf_digests=tuple((pointer, semantic_digest(value)) for pointer, value in {**source, **auth}.items()),
            provenance_reference="synthetic-observation",
            retiring_writer_handoff=context.maintenance_evidence.maintenance_id,
        )
        context = replace(context, migration_evidence=evidence)
        preview = registrar.preview(context.config_path, definition, context=context)
        assert preview.action is Action.ADOPT and not preview.config_changed
        assert preview.preserved_paths == ("/custom_setting",)
        validator.classify(preview)
        prepared = registrar.prepare(preview)
        result = registrar.apply(prepared, validator.approve(prepared))
        assert result.outcome is Outcome.APPLIED and not result.config_changed
        assert fixture.config_path.read_bytes() == before
        assert registrar.load_prepared(prepared.record_id, context=context, definition=definition)


@pytest.mark.parametrize("stage", ["prepare", "load", "apply"])
def test_generic_registrar_cannot_drop_consumer_policy(tmp_path, monkeypatch, stage):
    from snow_kit import bootstrap as snow
    monkeypatch.setattr(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION}))
    validator = SyntheticValidator()
    registrar = snow.registrars(maintenance_validator=validator)["cursor"]
    generic = CursorRegistrar(maintenance_validator=validator)
    definition = snow.registration_definition("d" * 40, "/opt/fixtures/snow", config_path=tmp_path / "profile.env")
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        context = bind(fixture.context, validator)
        preview = registrar.preview(context.config_path, definition, context=context)
        validator.classify(preview)
        if stage == "prepare":
            with pytest.raises(RegistrarError):
                generic.prepare(preview)
            assert not list(context.state_directory.glob("*.json"))
        else:
            prepared = registrar.prepare(preview)
            with pytest.raises(RegistrarError):
                if stage == "load":
                    generic.load_prepared(prepared.record_id, context=context, definition=definition)
                else:
                    generic.apply(prepared, validator.approve(prepared))
        assert not context.config_path.exists()


def test_consumer_policy_rechecks_forged_preview_and_durable_images(tmp_path, monkeypatch):
    from snow_kit import bootstrap as snow
    from kp_mcp_bootstrap.registrars.transactions import _prepared_payload
    monkeypatch.setattr(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION}))
    validator = SyntheticValidator()
    registrar = snow.registrars(maintenance_validator=validator)["cursor"]
    generic = CursorRegistrar(maintenance_validator=validator)
    definition = snow.registration_definition("d" * 40, "/opt/fixtures/snow", config_path=tmp_path / "profile.env")
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        context = bind(fixture.context, validator)
        prepared = prepared_example(registrar, definition, context, validator)
        assert registrar.apply(prepared, validator.approve(prepared)).outcome is Outcome.APPLIED
        data = json.loads(context.config_path.read_bytes())
        data["mcpServers"]["snow-kit"]["cwd"] = "/synthetic/prohibited"
        context.config_path.write_bytes(canonical_json_bytes(data))
        before = context.config_path.read_bytes()
        desired = snow.registration_definition("d" * 40, "/opt/fixtures/snow-new", config_path=tmp_path / "profile.env")
        context = bind(replace(context, definition_digest=desired.digest), validator)
        assert registrar.preview(context.config_path, desired, context=context).conflicts == (ReasonCode.POLICY_CONFLICT,)
        forged = generic.preview(context.config_path, desired, context=replace(context, policy_validator_id=None))
        forged = replace(forged, _private=replace(forged._private, context=context))
        forged = replace(forged, preview_digest=digest_value(forged.digest_payload()))
        validator.classify(forged)
        with pytest.raises(RegistrarError):
            registrar.prepare(forged)
        record = _prepared_payload(forged)
        record["payload_digest"] = digest_value(record)
        StateStore(context).prepared_path(forged.operation_id).write_bytes(canonical_json_bytes(record))
        with pytest.raises(RegistrarError):
            registrar.load_prepared(forged.operation_id, context=context, definition=desired)
        assert context.config_path.read_bytes() == before


@pytest.mark.parametrize("present", [False, True])
def test_maintenance_unregister_needs_receipt_bound_native_identity(tmp_path, monkeypatch, present):
    from snow_kit import bootstrap as snow
    monkeypatch.setattr(maintenance, "PERMITTED_CALLER_REVISIONS", frozenset({REVISION}))
    validator = SyntheticValidator()
    registrar = snow.registrars(maintenance_validator=validator)["cursor"]
    definition = snow.registration_definition("d" * 40, "/opt/fixtures/snow", config_path=tmp_path / "profile.env")
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        if present:
            fixture.config_path.write_text('{"mcpServers":{"snow-kit":{"command":"/opt/fixtures/snow"}}}')
        context = bind(fixture.context, validator, Action.UNREGISTER)
        before = context.config_path.read_bytes() if present else None
        preview = registrar.preview_unregister(context.config_path, context=context)
        assert preview.conflicts == (ReasonCode.OWNERSHIP_UNKNOWN,)
        forged = replace(preview, conflicts=())
        forged = replace(forged, preview_digest=digest_value(forged.digest_payload()))
        validator.classify(forged)
        with pytest.raises(RegistrarError):
            registrar.prepare(forged)
        assert not list(context.state_directory.glob("*.json"))
        assert (context.config_path.read_bytes() if present else None) == before


def test_recovery_preserves_already_resolved_ancestor_terminal(tmp_path, monkeypatch):
    from kp_mcp_bootstrap.registrars import operation_ref
    with example(tmp_path, monkeypatch) as (registrar, definition, context, validator):
        prepared = prepared_example(registrar, definition, context, validator)
        registrar.apply(prepared, validator.approve(prepared))
        store = StateStore(context)
        reference, _ = _bind_original_authority(store, _load_record_by_id(store, prepared.record_id))
        child = bind(context, validator, Action.ROLLBACK,
                     predecessor=context.maintenance_evidence.maintenance_id, recovery_of=reference)
        preview = registrar.rollback(operation_ref(prepared, maintenance_validator=validator), context=child)
        validator.classify(preview)
        inverse = registrar.prepare(preview)
        validator.reject_phase = "journal_committed"
        assert registrar.apply(inverse, validator.approve(inverse)).outcome is Outcome.RECOVERY_REQUIRED
        ancestor_terminal = store.read_optional(store.terminal_path(prepared.record_id))
        assert json.loads(ancestor_terminal)["result"]["config_changed"] is True
        validator.reject_phase = None
        reference, _ = _bind_original_authority(store, _load_record_by_id(store, inverse.record_id))
        grandchild = bind(child, validator, Action.RECOVER,
                          predecessor=child.maintenance_evidence.maintenance_id, recovery_of=reference)
        recovery = registrar.prepare_recovery(inverse, RecoveryDisposition.COMPLETE, context=grandchild)
        assert registrar.recover(recovery, RecoveryDisposition.COMPLETE,
                                 validator.approve(recovery)).outcome is Outcome.RECOVERED
        assert store.read_optional(store.terminal_path(prepared.record_id)) == ancestor_terminal
        assert registrar.preview(context.config_path, definition, context=bind(context, validator)).ready
