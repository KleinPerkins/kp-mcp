"""Independent closure proofs for target selection and durable terminal authority."""
from contextlib import contextmanager
import json
import uuid

import pytest

from kp_mcp_bootstrap.registrars import (
    CursorRegistrar, Inspection, Outcome, Preview, ReasonCode, RecoveryDisposition,
    RegistrarError, RegistrationDefinition, Result, SourceIdentity,
    fixture_approval, fixture_context, operation_ref,
)
from kp_mcp_bootstrap.registrars.contracts import digest_value
from kp_mcp_bootstrap.registrars.state import StateStore


@contextmanager
def target(tmp_path):
    registrar = CursorRegistrar()
    definition = RegistrationDefinition.stdio(
        SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:admission", "a" * 40, registrar.SERVER_NAME),
        command="/opt/fixtures/admission", args=(),
    )
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(registrar.preview(fixture.config_path, definition, context=fixture.context))
        yield registrar, definition, fixture, prepared, fixture_approval(prepared), StateStore(fixture.context)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def refusal(call, fixture, *, recovery=False):
    before = snapshot(fixture.root)
    expected = {ReasonCode.STATE_INVALID, ReasonCode.JOURNAL_INVALID, ReasonCode.RECOVERY_CONFLICT,
                ReasonCode.PREPARED_RECORD_REQUIRED, ReasonCode.PREIMAGE_CHANGED}
    try:
        result = call()
    except RegistrarError as error:
        assert error.code in expected
        if recovery:
            assert error.code is ReasonCode.RECOVERY_CONFLICT
    else:
        if isinstance(result, Preview):
            assert not result.ready and set(result.conflicts) & expected
        elif isinstance(result, Inspection):
            assert set(result.reason_codes) & expected
        elif isinstance(result, Result):
            assert result.outcome in {Outcome.CONFLICT, Outcome.FAILED, Outcome.RECOVERY_REQUIRED}
            assert set(result.reason_codes) & expected
            assert not result.config_changed and not result.state_changed
            if recovery:
                assert result.reason_codes[0] is ReasonCode.RECOVERY_CONFLICT
        else:
            pytest.fail(f"Invalid authority accepted as {type(result).__name__}")
    assert snapshot(fixture.root) == before


@pytest.mark.parametrize("phase", ["journal_prepared", "config_replaced", "receipt_verified"])
@pytest.mark.parametrize("tamper", ["target", "target_and_operation"])
@pytest.mark.parametrize("entrypoint", ["preview", "inspect", "withdraw", "prepare", "apply"])
def test_journal_selector_cannot_hide_authority_bound_to_actual_target(tmp_path, phase, tamper, entrypoint):
    with target(tmp_path) as (registrar, definition, fixture, original, approval, store):
        fresh_preview = registrar.preview(fixture.config_path, definition, context=fixture.context)
        fresh = registrar.prepare(fresh_preview)
        fresh_approval = fixture_approval(fresh)
        def interrupt(step):
            if step == phase:
                raise RuntimeError("fixture interruption")
        registrar._fault = interrupt
        assert registrar.apply(original, approval).outcome is Outcome.RECOVERY_REQUIRED
        registrar._fault = lambda _step: None
        path = store.journal_path(original.operation_id)
        journal = json.loads(path.read_bytes())
        journal["target_id"] = "0" * 64
        if tamper == "target_and_operation":
            journal["operation_id"] = str(uuid.uuid4())
        path.write_text(json.dumps(journal))
        calls = {
            "preview": lambda: registrar.preview(fixture.config_path, definition, context=fixture.context),
            "inspect": lambda: registrar.inspect_registration(fixture.config_path, context=fixture.context),
            "withdraw": lambda: registrar.preview_unregister(fixture.config_path, context=fixture.context),
            "prepare": lambda: registrar.prepare(fresh_preview),
            "apply": lambda: registrar.apply(fresh, fresh_approval),
        }
        refusal(calls[entrypoint], fixture)


TERMINAL_MUTATIONS = [
    ("result.config_changed", "yes"), ("result.state_changed", 1),
    ("result.next_action", {}), ("result.receipt_id", "0" * 64),
    ("result.verified_postimage", "0" * 64), ("result.recovery_id", "forged-recovery"),
    ("result.outcome", "recovery_required"),
    ("result.observations.registered.host", "foreign-host"),
    ("result.observations.registered.surface", "foreign-surface"),
    ("result.observations.registered.build", "foreign-build"),
    ("result.observations.registered.connection_revision", "b" * 40),
    ("result.observations.registered.evidence_reference", "unexpected-evidence"),
    ("target_binding", None),
]


@pytest.mark.parametrize("path,value", TERMINAL_MUTATIONS, ids=[item[0] for item in TERMINAL_MUTATIONS])
@pytest.mark.parametrize("entrypoint", ["preview", "inspect", "reference", "replay", "recover", "rollback"])
def test_coherently_rehashed_terminal_still_requires_closed_semantic_authority(tmp_path, path, value, entrypoint):
    with target(tmp_path) as (registrar, definition, fixture, original, approval, store):
        assert registrar.apply(original, approval).outcome is Outcome.APPLIED
        reference = operation_ref(original)
        terminal_path = store.terminal_path(original.operation_id)
        terminal = json.loads(terminal_path.read_bytes())
        node = terminal
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = ({"target_id": reference.target_id} if path == "target_binding" else value)
        terminal["terminal_digest"] = digest_value({key: item for key, item in terminal.items() if key != "terminal_digest"})
        terminal_path.write_text(json.dumps(terminal))
        calls = {
            "preview": lambda: registrar.preview(fixture.config_path, definition, context=fixture.context),
            "inspect": lambda: registrar.inspect_registration(fixture.config_path, context=fixture.context),
            "reference": lambda: operation_ref(original),
            "replay": lambda: registrar.apply(original, approval),
            "recover": lambda: registrar.recover(original, RecoveryDisposition.COMPLETE, approval),
            "rollback": lambda: registrar.rollback(reference, context=fixture.context),
        }
        refusal(calls[entrypoint], fixture, recovery=entrypoint == "recover")
