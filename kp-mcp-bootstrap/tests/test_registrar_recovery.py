"""Durable recovery and inverse-operation contracts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from kp_mcp_bootstrap.registrars import (
    CursorRegistrar,
    OperationRefKind,
    Outcome,
    ReasonCode,
    RecoveryDisposition,
    RegistrarError,
    RegistrationDefinition,
    SourceIdentity,
    fixture_approval,
    fixture_context,
    operation_ref,
    renew_fixture_context,
)
from kp_mcp_bootstrap.registrars.contracts import (
    canonical_json_bytes,
    digest_value,
    isoformat,
    parse_iso,
)


def _definition(
    revision: str = "b" * 40,
    command: str = "/opt/fixtures/recovery",
) -> RegistrationDefinition:
    return RegistrationDefinition.stdio(
        SourceIdentity(
            source_owner="KleinPerkins/kp-mcp",
            connection_id="kp-mcp:recovery-fixture",
            source_revision=revision,
            native_name="recovery-fixture",
        ),
        command=command,
        args=("mcp",),
    )


def _crash_at(registrar: CursorRegistrar, expected: str) -> None:
    def crash(step: str) -> None:
        if step == expected:
            raise RuntimeError("synthetic durable-step interruption")

    registrar._fault = crash  # type: ignore[method-assign]


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_recovered_terminal_binds_exact_resolving_operation(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        original_approval = fixture_approval(original)
        _crash_at(registrar, "config_replaced")
        assert (
            registrar.apply(original, original_approval).outcome
            is Outcome.RECOVERY_REQUIRED
        )
        registrar._fault = lambda _step: None  # type: ignore[method-assign]

        resolver = registrar.prepare_recovery(
            original, RecoveryDisposition.COMPLETE
        )
        unused_resolver = registrar.prepare_recovery(
            original, RecoveryDisposition.COMPLETE
        )
        assert (
            registrar.apply(resolver, fixture_approval(resolver)).outcome
            is Outcome.RECOVERED
        )

        terminal_path = (
            fixture.state_directory / f"terminal-{original.operation_id}.json"
        )
        terminal = json.loads(terminal_path.read_bytes())
        terminal["result"]["recovery_id"] = unused_resolver.operation_id
        payload = dict(terminal)
        payload.pop("terminal_digest")
        terminal["terminal_digest"] = digest_value(payload)
        terminal_path.write_bytes(canonical_json_bytes(terminal))
        terminal_path.chmod(0o600)

        before = _snapshot(fixture.root)
        entrypoints = (
            lambda: registrar.apply(original, original_approval),
            lambda: registrar.preview(
                fixture.config_path, definition, context=fixture.context
            ),
            lambda: registrar.inspect_registration(
                fixture.config_path, context=fixture.context
            ),
        )
        for entrypoint in entrypoints:
            with pytest.raises(RegistrarError) as caught:
                entrypoint()
            assert caught.value.code is ReasonCode.STATE_INVALID
            assert _snapshot(fixture.root) == before


@pytest.mark.parametrize(
    "phase,expected_config_change",
    [
        ("journal_prepared", True),
        ("config_replaced", False),
        ("receipt_verified", False),
    ],
)
def test_complete_recovery_uses_exact_saved_postimages(
    phase: str, expected_config_change: bool, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = fixture_approval(original)
        _crash_at(registrar, phase)
        interrupted = registrar.apply(original, approval)
        assert interrupted.outcome is Outcome.RECOVERY_REQUIRED
        registrar._fault = lambda _step: None  # type: ignore[method-assign]
        recovery = registrar.prepare_recovery(
            original, RecoveryDisposition.COMPLETE
        )
        result = registrar.recover(
            recovery,
            RecoveryDisposition.COMPLETE,
            fixture_approval(recovery),
        )
        assert result.outcome is Outcome.RECOVERED
        assert result.config_changed is expected_config_change
        assert registrar.inspect_registration(
            fixture.config_path, context=fixture.context
        ).owned_projection_match
        replay = registrar.apply(original, approval)
        assert replay.outcome is Outcome.NO_CHANGE


def test_cancel_pending_c0_r0_never_changes_config(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        _crash_at(registrar, "journal_prepared")
        assert registrar.apply(
            original, fixture_approval(original)
        ).outcome is Outcome.RECOVERY_REQUIRED
        registrar._fault = lambda _step: None  # type: ignore[method-assign]
        cancellation = registrar.prepare_recovery(
            original, RecoveryDisposition.CANCEL
        )
        result = registrar.recover(
            cancellation,
            RecoveryDisposition.CANCEL,
            fixture_approval(cancellation),
        )
        assert result.outcome is Outcome.CANCELLED
        assert not result.config_changed
        assert not fixture.config_path.exists()


def test_unapplied_preparation_has_explicit_cancel_action(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        cancellation = registrar.prepare_cancel(original)
        result = registrar.apply(cancellation, fixture_approval(cancellation))
        assert result.outcome is Outcome.CANCELLED
        assert not result.config_changed
        assert not fixture.config_path.exists()


def test_committed_and_interrupted_rollback_restore_exact_absence(
    tmp_path: Path,
) -> None:
    definition = _definition()
    for interrupted in (False, True):
        registrar = CursorRegistrar()
        with fixture_context(
            registrar, definition, fixture_root=tmp_path
        ) as fixture:
            original = registrar.prepare(
                registrar.preview(
                    fixture.config_path, definition, context=fixture.context
                )
            )
            if interrupted:
                _crash_at(registrar, "config_replaced")
                assert registrar.apply(
                    original, fixture_approval(original)
                ).outcome is Outcome.RECOVERY_REQUIRED
                registrar._fault = lambda _step: None  # type: ignore[method-assign]
            else:
                assert registrar.apply(
                    original, fixture_approval(original)
                ).outcome is Outcome.APPLIED
            ref = operation_ref(original, pending=interrupted)
            assert ref.kind is (
                OperationRefKind.PENDING_JOURNAL
                if interrupted
                else OperationRefKind.COMMITTED_RECEIPT
            )
            inverse = registrar.prepare(
                registrar.rollback(ref, context=fixture.context)
            )
            result = registrar.apply(inverse, fixture_approval(inverse))
            assert result.outcome is Outcome.ROLLED_BACK
            assert not fixture.config_path.exists()


@pytest.mark.parametrize("terminal_state", ["corrupt", "missing"])
def test_pending_rollback_ref_requires_actual_nonterminal_durable_state(
    terminal_state: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        assert registrar.apply(
            original, fixture_approval(original)
        ).outcome is Outcome.APPLIED
        committed_ref = operation_ref(original)
        terminal = fixture.state_directory / f"terminal-{original.operation_id}.json"
        if terminal_state == "corrupt":
            terminal.write_text(json.dumps({}) + "\n")
        else:
            terminal.unlink()

        if terminal_state == "corrupt":
            with pytest.raises(RegistrarError) as caught:
                operation_ref(original, pending=True)
            assert caught.value.code is ReasonCode.STATE_INVALID
            forged_pending = replace(
                committed_ref, kind=OperationRefKind.PENDING_JOURNAL
            )
            with pytest.raises(RegistrarError) as caught:
                registrar.rollback(forged_pending, context=fixture.context)
            assert caught.value.code is ReasonCode.RECOVERY_CONFLICT
        else:
            pending_ref = operation_ref(original, pending=True)
            assert pending_ref.kind is OperationRefKind.PENDING_JOURNAL
            recovery = registrar.prepare_recovery(
                original, RecoveryDisposition.COMPLETE
            )
            result = registrar.recover(
                recovery,
                RecoveryDisposition.COMPLETE,
                fixture_approval(recovery),
            )
            assert result.outcome is Outcome.RECOVERED
            assert result.config_changed is False


def test_committed_secondary_recovery_cannot_be_rolled_back_as_a_new_root(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        _crash_at(registrar, "config_replaced")
        assert registrar.apply(
            original, fixture_approval(original)
        ).outcome is Outcome.RECOVERY_REQUIRED
        registrar._fault = lambda _step: None  # type: ignore[method-assign]
        recovery = registrar.prepare_recovery(
            original, RecoveryDisposition.COMPLETE
        )
        assert registrar.apply(
            recovery, fixture_approval(recovery)
        ).outcome is Outcome.RECOVERED
        reference = operation_ref(recovery)
        with pytest.raises(RegistrarError) as caught:
            registrar.rollback(reference, context=fixture.context)
        assert caught.value.code is ReasonCode.RECOVERY_CONFLICT


@pytest.mark.parametrize("phase,ready", [("journal_prepared", False), ("receipt_verified", True)])
def test_pending_receipt_only_rollback_requires_applied_receipt_postimage(
    phase: str,
    ready: bool,
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    initial = _definition("a" * 40)
    updated = _definition("c" * 40)
    with fixture_context(registrar, initial, fixture_root=tmp_path) as fixture:
        first = registrar.prepare(
            registrar.preview(
                fixture.config_path, initial, context=fixture.context
            )
        )
        assert registrar.apply(first, fixture_approval(first)).outcome is Outcome.APPLIED
        update_context = replace(
            fixture.context,
            source_revision=updated.source_revision,
            definition_digest=updated.digest,
        )
        update = registrar.prepare(
            registrar.preview(
                fixture.config_path, updated, context=update_context
            )
        )
        assert update.config_changed is False
        _crash_at(registrar, phase)
        assert registrar.apply(
            update, fixture_approval(update)
        ).outcome is Outcome.RECOVERY_REQUIRED
        registrar._fault = lambda _step: None  # type: ignore[method-assign]
        inverse = registrar.rollback(
            operation_ref(update, pending=True), context=update_context
        )
        assert inverse.ready is ready
        if ready:
            rolled_back = registrar.prepare(inverse)
            assert registrar.apply(
                rolled_back, fixture_approval(rolled_back)
            ).outcome is Outcome.ROLLED_BACK
        else:
            assert inverse.conflicts == (ReasonCode.RECOVERY_CONFLICT,)


def test_pending_zero_change_operation_cannot_be_rolled_back(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        first = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        assert registrar.apply(first, fixture_approval(first)).outcome is Outcome.APPLIED
        zero_preview = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        assert zero_preview.config_changed is False
        assert zero_preview.state_changed is False
        zero = registrar.prepare(zero_preview)
        _crash_at(registrar, "journal_prepared")
        assert registrar.apply(
            zero, fixture_approval(zero)
        ).outcome is Outcome.RECOVERY_REQUIRED
        registrar._fault = lambda _step: None  # type: ignore[method-assign]
        inverse = registrar.rollback(
            operation_ref(zero, pending=True), context=fixture.context
        )
        assert inverse.conflicts == (ReasonCode.RECOVERY_CONFLICT,)


@pytest.mark.parametrize(
    "phase",
    ["journal_prepared", "config_replaced", "receipt_verified"],
)
@pytest.mark.parametrize(
    "tamper",
    [
        "issuer-authority",
        "issuer-reference",
        "audience",
        "audience-action",
        "action-digest",
        "payload-digest",
        "choice",
        "validated-before-issuance",
        "validated-after-expiry",
        "validated-malformed",
    ],
)
def test_fresh_recovery_cannot_launder_invalid_historical_approval(
    phase: str,
    tamper: str,
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = fixture_approval(original)
        _crash_at(registrar, phase)
        assert registrar.apply(original, approval).outcome is Outcome.RECOVERY_REQUIRED
        registrar._fault = lambda _step: None  # type: ignore[method-assign]

        journal_path = (
            fixture.state_directory / f"journal-{original.operation_id}.json"
        )
        journal = json.loads(journal_path.read_bytes())
        recorded = journal["approval"]
        if tamper == "issuer-authority":
            recorded["issuer_authority"] = "forged-fixture-issuer"
        elif tamper == "issuer-reference":
            recorded["issuer_reference"] = "forged-fixture-reference"
        elif tamper == "audience":
            recorded["audience"]["host"] = "forged-host"
        elif tamper == "audience-action":
            recorded["audience"]["action"] = "unregister"
        elif tamper == "action-digest":
            recorded["action_digest"] = "0" * 64
        elif tamper == "payload-digest":
            recorded["prepared_payload_digest"] = "0" * 64
        elif tamper == "choice":
            recorded["choice"] = "reuse"
        elif tamper == "validated-before-issuance":
            journal["approval_validated_at"] = isoformat(
                parse_iso(recorded["issued_at"]) - timedelta(seconds=1)
            )
        elif tamper == "validated-after-expiry":
            journal["approval_validated_at"] = isoformat(
                parse_iso(recorded["expires_at"]) + timedelta(seconds=1)
            )
        else:
            journal["approval_validated_at"] = "not-a-timestamp"
        journal_path.write_bytes(canonical_json_bytes(journal))
        journal_path.chmod(0o600)

        fresh = renew_fixture_context(fixture.context)
        before = _snapshot(fixture.root)
        with pytest.raises(RegistrarError) as caught:
            registrar.prepare_recovery(
                original,
                RecoveryDisposition.COMPLETE,
                context=fresh,
            )
        assert caught.value.code is ReasonCode.RECOVERY_CONFLICT
        assert _snapshot(fixture.root) == before
