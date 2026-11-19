"""Prepared registrar operations, durable apply, and batch preflight."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError

from .contracts import (
    ABSENT_DIGEST,
    context_from_record, maintenance_provenance, versioned_schema,
    PREPARED_SCHEMA,
    Action,
    Approval,
    ApprovalAudience,
    AuthKind,
    BatchApplyRequest,
    BatchPreflight,
    BatchPreviewRequest,
    ObservationStatus,
    Observations,
    OperationRef,
    OperationRefKind,
    Outcome,
    OwnedLeafAction,
    PreparedOperation,
    Preview,
    PreviewPrivate,
    RecoveryDisposition,
    RegistrationContext,
    RegistrationDefinition,
    Result,
    canonical_json_bytes,
    digest_bytes,
    digest_value,
    isoformat,
    new_operation_id,
    strict_json_loads,
    utc_now,
)
from .durable_validation import (
    FIXTURE_ISSUER,
    _versioned_keys, _validate_v2_prepared,
    JOURNAL_SCHEMA,
    PREPARED_RECORD_SCHEMA,
    TERMINAL_SCHEMA,
    _JOURNAL_KEYS,
    _PREPARED_KEYS,
    _SECONDARY_ACTIONS,
    _bind_original_authority,
    _current_pair,
    _decoded,
    _encoded,
    _image_digest,
    _load_original_journal,
    _load_record_by_id,
    _original_action_digest,
    _prepared_from_record,
    _read_valid_terminal,
    _receipt_owned_snapshot,
    _recorded_approval,
    _validate_admission_terminal,
    _validate_terminal,
    validate_target_operation_admission,
)
from .state import (
    StateStore,
    TargetBinding,
    atomic_replace_target,
    inspect_target,
    read_target,
)
from .writer_window import validate_writer_window
from .maintenance import validate_runtime, APPROVAL_ISSUER


def _validator(registrar: Any) -> Any:
    return getattr(registrar, "_maintenance_validator", None)


def _result_provenance(context: RegistrationContext) -> dict[str, Any]:
    return {"schema": versioned_schema("kp-mcp/registrar-result/v1", context), **maintenance_provenance(context)}


def _lineage(context: RegistrationContext, original: Mapping[str, Any]) -> None:
    original_context = context_from_record(original["context"])
    if context.maintenance_evidence is None:
        if original_context.maintenance_evidence is not None:
            raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED)
        return
    evidence = context.maintenance_evidence
    if (original_context.maintenance_evidence is None
        or evidence.predecessor_maintenance_id != original_context.maintenance_evidence.maintenance_id
        or context.source_revision != original_context.source_revision
        or context.build != original_context.build):
        raise RegistrarError(ReasonCode.RECOVERY_CONFLICT)


def _mutation_guard(
    registrar: Any, context: RegistrationContext, record: Mapping[str, Any],
    phase: str, config: bytes | None, receipt: bytes | None,
    *, prepared: PreparedOperation | None = None, approval: Approval | None = None,
) -> None:
    if context.maintenance_evidence is None:
        return
    audience = ApprovalAudience(context.source_owner, context.connection_id, context.host, context.scope,
                                record["preview"]["target_id"], Action(record["action"]))
    validate_runtime(
        context, _validator(registrar), phase=phase, audience=audience,
        operation_id=record["operation_id"],
        action_digest=prepared.action_digest if prepared else None,
        prepared_payload_digest=prepared.payload_digest if prepared else digest_value(record),
        expected_config_digest=_image_digest(config), expected_state_digest=_image_digest(receipt),
        original_operation_reference=record["preview"]["private_recovery_reference"], approval=approval,
        durable_material=tuple(_decoded(record[key]) for key in ("config_preimage", "config_postimage", "receipt_preimage", "receipt_postimage")),
    )
    store = StateStore(context)
    binding = inspect_target(context.config_path)
    if read_target(binding) != config or store.read_optional(store.receipt_path(binding.target_id)) != receipt:
        raise RegistrarError(ReasonCode.PREIMAGE_CHANGED, target_id=context.target_id)


def build_preview(
    *,
    action: Action,
    registrar: Any,
    definition: RegistrationDefinition | None,
    context: RegistrationContext,
    binding: TargetBinding,
    config_preimage: bytes | None,
    config_postimage: bytes | None,
    receipt_preimage: bytes | None,
    receipt_postimage: bytes | None,
    owned_actions: Sequence[OwnedLeafAction],
    preserved_paths: Sequence[str],
    conflicts: Sequence[ReasonCode],
    original_operation_id: str | None = None,
    recovery_disposition: Any = None,
    journal_preimage: bytes | None = None,
    private_recovery_reference: str | None = None,
    operation_id: str | None = None,
) -> Preview:
    operation_id = operation_id or new_operation_id()
    now = utc_now()
    expires_at = now + registrar.PREVIEW_LIFETIME
    if context.writer_window and context.writer_window.expires_at < expires_at:
        expires_at = context.writer_window.expires_at
    private = PreviewPrivate(
        config_preimage=config_preimage,
        config_postimage=config_postimage,
        receipt_preimage=receipt_preimage,
        receipt_postimage=receipt_postimage,
        context=context,
        definition=definition,
        logical_path=binding.logical_path,
        resolved_path=binding.resolved_path,
        link_binding=binding.to_record(),
        original_operation_id=original_operation_id,
        recovery_disposition=recovery_disposition,
    )
    preview = Preview(
        schema=versioned_schema("kp-mcp/registrar-preview/v1", context),
        operation_id=operation_id,
        action=action,
        definition_digest=definition.digest if definition else context.definition_digest,
        source_owner=context.source_owner,
        source_revision=context.source_revision,
        connection_id=context.connection_id,
        adapter_version=registrar.ADAPTER_VERSION,
        mapping_digest=registrar.mapping_digest,
        host=context.host,
        surface=context.surface,
        build=context.build,
        scope=context.scope,
        target_id=binding.target_id,
        config_preimage=_image_digest(config_preimage),
        receipt_preimage=_image_digest(receipt_preimage),
        journal_preimage=_image_digest(journal_preimage),
        desired_config=_image_digest(config_postimage),
        desired_receipt=_image_digest(receipt_postimage),
        owned_leaf_actions=tuple(owned_actions),
        preserved_paths=tuple(sorted(preserved_paths)),
        conflicts=tuple(dict.fromkeys(conflicts)),
        private_recovery_reference=private_recovery_reference,
        auth_binding_digest=(
            context.auth_binding.digest if context.auth_binding else "not_applicable"
        ),
        writer_window_digest=(
            context.writer_window.digest if context.writer_window else None
        ),
        expires_at=expires_at,
        preview_digest="",
        config_changed=config_preimage != config_postimage,
        state_changed=receipt_preimage != receipt_postimage,
        _private=private,
    )
    return replace(preview, preview_digest=digest_value(preview.digest_payload()))


def _prepared_payload(preview: Preview) -> dict[str, Any]:
    private = preview._private
    return {
        "schema": versioned_schema(PREPARED_RECORD_SCHEMA, private.context),
        **maintenance_provenance(private.context),
        "record_id": preview.operation_id,
        "operation_id": preview.operation_id,
        "action": preview.action.value,
        "preview": preview.to_dict(),
        "config_preimage": _encoded(private.config_preimage),
        "config_postimage": _encoded(private.config_postimage),
        "receipt_preimage": _encoded(private.receipt_preimage),
        "receipt_postimage": _encoded(private.receipt_postimage),
        "context": private.context.to_record(),
        "definition": private.definition.to_record() if private.definition else None,
        "logical_path": str(private.logical_path),
        "resolved_path": str(private.resolved_path),
        "link_binding": dict(private.link_binding),
        "original_operation_id": private.original_operation_id,
        "recovery_disposition": (
            private.recovery_disposition.value if private.recovery_disposition else None
        ),
        "expires_at": isoformat(preview.expires_at),
    }


def prepare(preview: Preview, *, registrar: Any = None) -> PreparedOperation:
    if digest_value(preview.digest_payload()) != preview.preview_digest:
        raise RegistrarError(
            ReasonCode.STALE_PREVIEW,
            target_id=preview.target_id,
            operation_id=preview.operation_id,
        )
    if preview.conflicts:
        raise RegistrarError(
            preview.conflicts[0],
            target_id=preview.target_id,
            operation_id=preview.operation_id,
        )
    if utc_now() > preview.expires_at:
        raise RegistrarError(
            ReasonCode.STALE_PREVIEW,
            target_id=preview.target_id,
            operation_id=preview.operation_id,
        )
    context = preview._private.context
    validate_writer_window(
        context, resolved_target=preview._private.resolved_path, maintenance_validator=_validator(registrar)
    )
    store = StateStore(context)
    payload = _prepared_payload(preview)
    _validate_v2_prepared({**payload, "payload_digest": digest_value(payload)})
    _validate_active_registrar(registrar, context, payload)
    _mutation_guard(registrar, context, payload, "prepare", preview._private.config_preimage, preview._private.receipt_preimage)
    payload_digest = digest_value(payload)
    encoded_payload = canonical_json_bytes({**payload, "payload_digest": payload_digest})
    try:
        with store.lock(preview.target_id):
            validate_target_operation_admission(
                context,
                preview.target_id,
                action=preview.action,
                original_operation_id=preview._private.original_operation_id,
                store=store,
            )
            _mutation_guard(registrar, context, payload, "prepare_locked", preview._private.config_preimage, preview._private.receipt_preimage)
            _validate_active_registrar(registrar, context, payload)
            state_changed = store.write(
                store.prepared_path(preview.operation_id), encoded_payload
            )
    except RegistrarError:
        raise
    except OSError:
        raise RegistrarError(
            ReasonCode.WRITE_FAILED,
            target_id=context.target_id,
            operation_id=preview.operation_id,
        ) from None
    audience = ApprovalAudience(
        source_owner=context.source_owner,
        connection_id=context.connection_id,
        host=context.host,
        scope=context.scope,
        target_id=preview.target_id,
        action=preview.action,
    )
    action_digest = digest_value(
        {
            "payload_digest": payload_digest,
            "redacted_preview": preview.to_dict(),
        }
    )
    return PreparedOperation(
        schema=versioned_schema(PREPARED_SCHEMA, context),
        record_id=preview.operation_id,
        payload_digest=payload_digest,
        operation_id=preview.operation_id,
        action_digest=action_digest,
        action=preview.action,
        audience=audience,
        state_changed=state_changed,
        config_changed=False,
        expires_at=preview.expires_at,
        _state_directory=context.state_directory,
        _context=context,
        _definition=preview._private.definition,
    )


def load_prepared(
    registrar: Any, record_id: str, *, context: RegistrationContext,
    definition: RegistrationDefinition | None,
) -> PreparedOperation:
    """Reload exact staged bytes with explicit caller authority and source data."""
    validate_writer_window(context, maintenance_validator=_validator(registrar))
    # UUID form prevents caller-controlled state paths before opening a record.
    from uuid import UUID
    try:
        if str(UUID(record_id)) != record_id:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise RegistrarError(ReasonCode.PREPARED_RECORD_REQUIRED) from None
    record = _load_record_by_id(StateStore(context), record_id)
    prepared = replace(_prepared_from_record(record, context), _definition=definition)
    if record["definition"] != (definition.to_record() if definition else None):
        raise RegistrarError(ReasonCode.OWNER_CONFLICT)
    active = None if context.to_record() == prepared._context.to_record() else context
    _load_prepared(prepared, access_context=active, maintenance_validator=_validator(registrar))
    _validate_active_registrar(registrar, context, record)
    return prepared


def _validate_active_registrar(registrar: Any, context: RegistrationContext, record: Mapping[str, Any]) -> None:
    if context.maintenance_evidence is None:
        return
    from .durable_validation import _validate_v2_images

    if registrar is None:
        raise RegistrarError(ReasonCode.OWNER_CONFLICT, target_id=context.target_id)
    record = strict_json_loads(canonical_json_bytes(record))
    definition = RegistrationDefinition.from_record(record["definition"]) if record["definition"] is not None else None
    registrar._validate_context(context.config_path, context, definition)
    try:
        _validate_v2_images(record, context_from_record(record["context"]), registrar=registrar)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id) from None
    for key in ("config_preimage", "config_postimage"):
        registrar._validate_policy_bytes(_decoded(record[key]), definition, context)


def fixture_approval(
    prepared: PreparedOperation,
    *,
    issuer_reference: str | None = None,
    now: Any = None,
) -> Approval:
    context = prepared._context
    validate_writer_window(context)
    if not context.writer_window or context.writer_window.mechanism != "fixture-isolation":
        raise RegistrarError(
            ReasonCode.APPROVAL_INVALID,
            target_id=context.target_id,
            operation_id=prepared.operation_id,
        )
    issued = now or utc_now()
    reference = issuer_reference or context.writer_window.acquisition_reference
    if reference != context.writer_window.acquisition_reference:
        raise RegistrarError(
            ReasonCode.APPROVAL_INVALID,
            target_id=context.target_id,
            operation_id=prepared.operation_id,
        )
    return Approval(
        audience=prepared.audience,
        operation_id=prepared.operation_id,
        action_digest=prepared.action_digest,
        prepared_payload_digest=prepared.payload_digest,
        issuer_authority=FIXTURE_ISSUER,
        issuer_reference=reference,
        issued_at=issued,
        expires_at=min(prepared.expires_at, context.writer_window.expires_at),
        choice="apply",
    )


def _validate_approval(
    prepared: PreparedOperation,
    approval: Approval,
    *,
    checked_at: datetime | None = None,
    maintenance_validator: Any = None,
) -> datetime:
    context = prepared._context
    now = checked_at or utc_now()
    validate_writer_window(context, checked_at=now, maintenance_validator=maintenance_validator)
    window = context.writer_window
    if window is None:  # closed by validate_writer_window; keeps narrowing explicit
        raise RegistrarError(
            ReasonCode.APPROVAL_INVALID,
            target_id=prepared.audience.target_id,
            operation_id=prepared.operation_id,
        )
    if (
        approval.audience != prepared.audience
        or approval.operation_id != prepared.operation_id
        or approval.action_digest != prepared.action_digest
        or approval.prepared_payload_digest != prepared.payload_digest
        or approval.choice != "apply"
        or approval.issuer_authority != (APPROVAL_ISSUER if context.maintenance_evidence else FIXTURE_ISSUER)
        or approval.issuer_reference != window.acquisition_reference
        or approval.issued_at < window.acquired_at
        or approval.issued_at > now
        or approval.expires_at < now
        or approval.expires_at > prepared.expires_at
        or approval.expires_at > window.expires_at
        or approval.expires_at < approval.issued_at
    ):
        raise RegistrarError(
            ReasonCode.APPROVAL_INVALID,
            target_id=prepared.audience.target_id,
            operation_id=prepared.operation_id,
        )
    if context.maintenance_evidence is not None:
        validate_runtime(context, maintenance_validator, phase="approval", audience=prepared.audience,
                         operation_id=prepared.operation_id, action_digest=prepared.action_digest,
                         prepared_payload_digest=prepared.payload_digest, approval=approval, checked_at=now)
    return now


def _load_prepared(
    prepared: PreparedOperation,
    *,
    access_context: RegistrationContext | None = None,
    maintenance_validator: Any = None,
) -> tuple[dict[str, Any], StateStore]:
    context = prepared._context
    active_context = access_context or context
    validate_writer_window(active_context, maintenance_validator=maintenance_validator)
    if access_context is not None:
        embedded = context.to_record()
        supplied = access_context.to_record()
        if active_context.maintenance_evidence is not None:
            if context.maintenance_evidence is None or active_context.maintenance_evidence.predecessor_maintenance_id != context.maintenance_evidence.maintenance_id:
                raise RegistrarError(ReasonCode.RECOVERY_CONFLICT)
            for key in ("maintenance_evidence", "concurrency_claim", "writer_window_digest", "maintenance_evidence_digest"):
                embedded.pop(key, None)
                supplied.pop(key, None)
        embedded.pop("writer_window", None)
        supplied.pop("writer_window", None)
        if embedded != supplied:
            raise RegistrarError(
                ReasonCode.OWNER_CONFLICT,
                target_id=context.target_id,
                operation_id=prepared.operation_id,
            )
    store = StateStore(active_context)
    data = store.read_optional(store.prepared_path(prepared.record_id))
    if data is None:
        raise RegistrarError(
            ReasonCode.PREPARED_RECORD_REQUIRED,
            target_id=context.target_id,
            operation_id=prepared.operation_id,
        )
    try:
        record = strict_json_loads(data)
    except (ValueError, TypeError, UnicodeError):
        raise RegistrarError(
            ReasonCode.STATE_INVALID,
            target_id=context.target_id,
            operation_id=prepared.operation_id,
        ) from None
    if not isinstance(record, dict) or set(record) != _versioned_keys(_PREPARED_KEYS, record):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
    supplied_digest = record.pop("payload_digest")
    expected_action_digest = digest_value(
        {
            "payload_digest": supplied_digest,
            "redacted_preview": record.get("preview"),
        }
    )
    expected_audience = {
        "source_owner": record.get("context", {}).get("source_owner"),
        "connection_id": record.get("context", {}).get("connection_id"),
        "host": record.get("context", {}).get("host"),
        "scope": record.get("context", {}).get("scope"),
        "target_id": record.get("preview", {}).get("target_id"),
        "action": record.get("action"),
    }
    if (
        record.get("schema") != versioned_schema(PREPARED_RECORD_SCHEMA, context)
        or digest_value(record) != supplied_digest
        or supplied_digest != prepared.payload_digest
        or record.get("record_id") != prepared.record_id
        or record.get("operation_id") != prepared.operation_id
        or record.get("action") != prepared.action.value
        or prepared.schema != versioned_schema(PREPARED_SCHEMA, context)
        or prepared.action_digest != expected_action_digest
        or prepared.audience.to_record() != expected_audience
        or isoformat(prepared.expires_at) != record.get("expires_at")
        or prepared.config_changed is not False
        or prepared._state_directory.absolute()
        != context.state_directory.absolute()
        or canonical_json_bytes(record.get("context"))
        != canonical_json_bytes(context.to_record())
        or (
            record.get("definition")
            != (prepared._definition.to_record() if prepared._definition else None)
        )
    ):
        raise RegistrarError(
            ReasonCode.STATE_INVALID,
            target_id=context.target_id,
            operation_id=prepared.operation_id,
        )
    record["payload_digest"] = supplied_digest
    _validate_v2_prepared(record)
    validate_writer_window(
        active_context, resolved_target=Path(record["resolved_path"]), maintenance_validator=maintenance_validator
    )
    return record, store


def _result_from_terminal(
    prepared: PreparedOperation,
    terminal: Mapping[str, Any],
    *,
    disposition: RecoveryDisposition | None = None,
) -> Result:
    result = terminal["result"]
    context = prepared._context
    stored_outcome = Outcome(result["outcome"])
    if disposition is RecoveryDisposition.CANCEL:
        if stored_outcome is not Outcome.CANCELLED:
            raise RegistrarError(
                ReasonCode.RECOVERY_CONFLICT,
                operation_id=prepared.operation_id,
            )
        replay_outcome = Outcome.CANCELLED
    elif disposition is RecoveryDisposition.COMPLETE:
        if stored_outcome is Outcome.CANCELLED or (
            stored_outcome is Outcome.ROLLED_BACK
            and prepared.action is not Action.ROLLBACK
        ):
            raise RegistrarError(
                ReasonCode.RECOVERY_CONFLICT,
                operation_id=prepared.operation_id,
            )
        replay_outcome = Outcome.NO_CHANGE
    elif prepared.action is Action.CANCEL and stored_outcome is Outcome.CANCELLED:
        replay_outcome = Outcome.CANCELLED
    elif prepared.action is Action.ROLLBACK and stored_outcome is Outcome.ROLLED_BACK:
        replay_outcome = Outcome.ROLLED_BACK
    elif prepared.action is Action.RECOVER and stored_outcome in {
        Outcome.RECOVERED,
        Outcome.CANCELLED,
    }:
        replay_outcome = stored_outcome
    elif stored_outcome in {Outcome.APPLIED, Outcome.NO_CHANGE, Outcome.RECOVERED}:
        replay_outcome = Outcome.NO_CHANGE
    else:
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            operation_id=prepared.operation_id,
        )
    if terminal["journal_phase"] == "cancelled":
        registered = (
            ObservationStatus.FAIL
            if terminal["receipt_postimage"] == ABSENT_DIGEST
            else ObservationStatus.PASS
        )
    else:
        registered = (
            ObservationStatus.FAIL
            if _decoded(terminal["receipt_postimage"]) is None
            else ObservationStatus.PASS
        )
    return Result(
        **_result_provenance(prepared._context),
        operation_id=result["operation_id"],
        action_digest=result["action_digest"],
        action=Action(result["action"]),
        outcome=replay_outcome,
        config_changed=False,
        state_changed=False,
        verified_postimage=result["verified_postimage"],
        receipt_id=result["receipt_id"],
        recovery_id=result["recovery_id"],
        reason_codes=tuple(ReasonCode(code) for code in result["reason_codes"]),
        conflicts=tuple(ReasonCode(code) for code in result["conflicts"]),
        next_action=result["next_action"],
        observations=Observations.with_registered(context, registered),
    )


def preflight_apply(
    registrar: Any,
    prepared: PreparedOperation,
    approval: Approval,
    *,
    path: Path | None = None,
    definition: RegistrationDefinition | None = None,
    context: RegistrationContext | None = None,
    intended_action: Action | None = None,
    approval_checked_at: datetime | None = None,
) -> tuple[dict[str, Any], StateStore, TargetBinding, Result | None]:
    bound_context = prepared._context
    if context is not None and context.to_record() != bound_context.to_record():
        raise RegistrarError(ReasonCode.OWNER_CONFLICT, target_id=bound_context.target_id)
    if path is not None and path.absolute() != bound_context.config_path.absolute():
        raise RegistrarError(ReasonCode.TARGET_CHANGED, target_id=bound_context.target_id)
    if definition is not None:
        bound_context.validate_definition(definition)
        if prepared._definition is None or definition.to_record() != prepared._definition.to_record():
            raise RegistrarError(ReasonCode.OWNER_CONFLICT, target_id=bound_context.target_id)
    if registrar.mapping_digest != bound_context.mapping_digest:
        raise RegistrarError(ReasonCode.UNSUPPORTED_FIELD, target_id=bound_context.target_id)
    if intended_action is Action.REGISTER:
        if prepared.action not in {Action.REGISTER, Action.ADOPT}:
            raise RegistrarError(ReasonCode.APPROVAL_INVALID, target_id=bound_context.target_id)
    elif intended_action is not None and prepared.action is not intended_action:
        raise RegistrarError(ReasonCode.APPROVAL_INVALID, target_id=bound_context.target_id)
    checked_at = approval_checked_at or utc_now()
    _validate_approval(prepared, approval, checked_at=checked_at, maintenance_validator=_validator(registrar))
    if checked_at > prepared.expires_at:
        raise RegistrarError(ReasonCode.STALE_PREVIEW, target_id=bound_context.target_id)
    record, store = _load_prepared(prepared, maintenance_validator=_validator(registrar))
    _validate_active_registrar(registrar, bound_context, record)
    validate_target_operation_admission(
        bound_context,
        record["preview"]["target_id"],
        action=prepared.action,
        original_operation_id=record["original_operation_id"],
        store=store,
    )
    terminal_data = store.read_optional(store.terminal_path(prepared.operation_id))
    if terminal_data is not None:
        try:
            terminal = strict_json_loads(terminal_data)
        except (ValueError, TypeError, UnicodeError):
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=bound_context.target_id) from None
        binding = _validate_terminal(prepared, record, store, terminal)
        return record, store, binding, _result_from_terminal(prepared, terminal)
    _revalidate_original_authority(store, record)
    binding = inspect_target(bound_context.config_path)
    if binding.to_record() != record["link_binding"]:
        raise RegistrarError(ReasonCode.TARGET_CHANGED, target_id=bound_context.target_id)
    if read_target(binding) != _decoded(record["config_preimage"]):
        raise RegistrarError(ReasonCode.PREIMAGE_CHANGED, target_id=bound_context.target_id)
    target_id = record["preview"]["target_id"]
    if store.read_optional(store.receipt_path(target_id)) != _decoded(record["receipt_preimage"]):
        raise RegistrarError(ReasonCode.PREIMAGE_CHANGED, target_id=bound_context.target_id)
    journal = store.read_optional(store.journal_path(prepared.operation_id))
    if journal is not None:
        raise RegistrarError(ReasonCode.RECOVERY_CONFLICT, target_id=bound_context.target_id)
    registrar._validate_policy_bytes(
        _decoded(record["config_preimage"]),
        prepared._definition,
        bound_context,
    )
    return record, store, binding, None


def _journal_record(
    prepared: PreparedOperation,
    record: Mapping[str, Any],
    *,
    phase: str,
    approval: Approval,
    approval_validated_at: Any,
) -> dict[str, Any]:
    return {
        "schema": versioned_schema(JOURNAL_SCHEMA, prepared._context),
        **maintenance_provenance(prepared._context),
        "operation_id": prepared.operation_id,
        "payload_digest": prepared.payload_digest,
        "action_digest": prepared.action_digest,
        "action": prepared.action.value,
        "phase": phase,
        "target_id": prepared.audience.target_id,
        "config_preimage": record["config_preimage"],
        "config_postimage": record["config_postimage"],
        "receipt_preimage": record["receipt_preimage"],
        "receipt_postimage": record["receipt_postimage"],
        "link_binding": record["link_binding"],
        "original_operation_id": record["original_operation_id"],
        "approval": approval.to_dict(),
        "approval_validated_at": isoformat(approval_validated_at),
    }


def _terminal_payload(
    *,
    operation_id: str,
    payload_digest: str,
    action_digest: str,
    action: Action,
    result: Result,
    config_postimage: str | None,
    receipt_postimage: str | None,
    target_binding: TargetBinding,
    journal_phase: str,
    journal_data: bytes,
) -> dict[str, Any]:
    payload = {
        "schema": TERMINAL_SCHEMA[:-1] + "2" if result.schema.endswith("/v2") else TERMINAL_SCHEMA,
        **({key: result.to_dict()[key] for key in ("concurrency_claim", "writer_window_digest", "maintenance_evidence_digest")} if result.schema.endswith("/v2") else {}),
        "operation_id": operation_id,
        "payload_digest": payload_digest,
        "action_digest": action_digest,
        "action": action.value,
        "config_postimage": config_postimage,
        "receipt_postimage": receipt_postimage,
        "target_binding": target_binding.to_record(),
        "journal_phase": journal_phase,
        "journal_digest": digest_bytes(journal_data),
        "result": result.to_dict(),
    }
    return {**payload, "terminal_digest": digest_value(payload)}


def _terminal_record(
    prepared: PreparedOperation,
    result: Result,
    **kwargs: Any,
) -> dict[str, Any]:
    return _terminal_payload(
        operation_id=prepared.operation_id,
        payload_digest=prepared.payload_digest,
        action_digest=prepared.action_digest,
        action=prepared.action,
        result=result,
        **kwargs,
    )


def _terminalize_original(
    registrar: Any,
    store: StateStore,
    prepared: PreparedOperation,
    secondary_record: Mapping[str, Any],
    secondary_result: Result,
    approval: Approval,
    *, authority_prepared: PreparedOperation | None = None,
    authority_record: Mapping[str, Any] | None = None,
    resolving: frozenset[str] = frozenset(),
) -> None:
    if prepared.operation_id in resolving:
        raise RegistrarError(ReasonCode.RECOVERY_CONFLICT)
    active_prepared = authority_prepared or prepared
    active_record = authority_record or secondary_record
    original_id = secondary_record.get("original_operation_id")
    if not original_id:
        return
    original = _load_record_by_id(store, original_id)
    # Completing an interrupted secondary operation must also complete its
    # predecessor bookkeeping under the *fresh child's* authority. No expired
    # record is renewed, and already removed cancellation staging is not rebuilt.
    if (active_prepared._context.maintenance_evidence is not None
        and prepared.action is Action.RECOVER
        and secondary_record.get("recovery_disposition") == RecoveryDisposition.COMPLETE.value
        and original.get("original_operation_id") is not None):
        parent_id = original["original_operation_id"]
        if store.read_optional(store.prepared_path(parent_id)) is not None:
            from .durable_validation import _partial_resolution_child, _validate_admission_terminal

            parent = _load_record_by_id(store, parent_id)
            parent_journal_data = store.read_optional(store.journal_path(parent_id))
            parent_terminal_data = store.read_optional(store.terminal_path(parent_id))
            resolved_by_child = False
            if parent_terminal_data is not None and parent_journal_data is not None:
                try:
                    parent_terminal = _validate_admission_terminal(
                        store=store, context=context_from_record(parent["context"]),
                        journal=_load_original_journal(store, parent), journal_data=parent_journal_data,
                        terminal_data=parent_terminal_data, record=parent,
                        target_id=parent["preview"]["target_id"],
                    )
                    resolved_by_child = parent_terminal["result"]["recovery_id"] == original_id
                except RegistrarError:
                    # An exact admitted partial transition is checked below.
                    pass
            if resolved_by_child:
                if parent_terminal["journal_phase"] == "cancelled":
                    _mutation_guard(registrar, active_prepared._context, active_record, "cancel_staging_remove",
                        _decoded(active_record["config_postimage"]), _decoded(active_record["receipt_postimage"]),
                        prepared=active_prepared, approval=approval)
                    store.remove(store.prepared_path(parent_id))
            else:
                # The parent must be either the child's exact still-unmodified
                # authority snapshot or its uniquely admitted partial transition.
                try:
                    parent_reference, parent_prior_journal = _bind_original_authority(store, parent)
                    unchanged = (parent_reference == original["preview"]["private_recovery_reference"]
                                 and _image_digest(parent_prior_journal) == original["preview"]["journal_preimage"])
                except RegistrarError:
                    unchanged = False
                if not unchanged and (parent_journal_data is None or _partial_resolution_child(
                    store, parent, strict_json_loads(parent_journal_data), parent_terminal_data
                ) != original_id):
                    raise RegistrarError(ReasonCode.RECOVERY_CONFLICT, operation_id=parent_id)
            old_prepared = _prepared_from_record(original, store.context)
            old_action = Action(original["action"])
            old_cancel = old_action is Action.CANCEL or (old_action is Action.RECOVER and original.get("recovery_disposition") == "cancel")
            old_result = replace(secondary_result, operation_id=old_prepared.operation_id,
                action_digest=old_prepared.action_digest, action=old_action,
                outcome=Outcome.CANCELLED if old_cancel else Outcome.ROLLED_BACK if old_action is Action.ROLLBACK else Outcome.RECOVERED,
                config_changed=original["config_preimage"] != original["config_postimage"],
                recovery_id=old_prepared.operation_id if old_action is Action.RECOVER else None,
                **_result_provenance(old_prepared._context))
            if not resolved_by_child:
                _terminalize_original(registrar, store, old_prepared, original, old_result, approval,
                    authority_prepared=active_prepared, authority_record=active_record,
                    resolving=resolving | {prepared.operation_id})
    cancellation = prepared.action is Action.CANCEL or (
        prepared.action is Action.RECOVER
        and secondary_record.get("recovery_disposition")
        == RecoveryDisposition.CANCEL.value
    )
    if prepared.action is Action.ROLLBACK:
        outcome = Outcome.ROLLED_BACK
        phase = "rolled_back"
    elif cancellation:
        outcome = Outcome.CANCELLED
        phase = "cancelled"
    else:
        outcome = Outcome.RECOVERED
        phase = "committed"
    original_result = Result(
        **_result_provenance(context_from_record(original["context"])),
        operation_id=original_id,
        action_digest=_original_action_digest(original),
        action=Action(original["action"]),
        outcome=outcome,
        config_changed=secondary_result.config_changed,
        state_changed=True,
        verified_postimage=secondary_result.verified_postimage,
        receipt_id=secondary_result.receipt_id,
        recovery_id=prepared.operation_id,
        reason_codes=(),
        conflicts=(),
        next_action=(
            "The original operation is terminal and cannot be replayed."
        ),
        observations=secondary_result.observations,
    )
    journal_path = store.journal_path(original_id)
    journal_data = store.read_optional(journal_path)
    if journal_data is None:
        if prepared.action is not Action.CANCEL:
            raise RegistrarError(ReasonCode.JOURNAL_INVALID, operation_id=original_id)
        journal = {
            "schema": versioned_schema(JOURNAL_SCHEMA, context_from_record(original["context"])),
            **maintenance_provenance(context_from_record(original["context"])),
            "operation_id": original_id,
            "payload_digest": original["payload_digest"],
            "action_digest": _original_action_digest(original),
            "action": original["action"],
            "phase": phase,
            "target_id": original["preview"]["target_id"],
            "config_preimage": original["config_preimage"],
            "config_postimage": original["config_postimage"],
            "receipt_preimage": original["receipt_preimage"],
            "receipt_postimage": original["receipt_postimage"],
            "link_binding": original["link_binding"],
            "original_operation_id": original["original_operation_id"],
            "approval": None,
            "approval_validated_at": None,
        }
    else:
        try:
            journal = strict_json_loads(journal_data)
        except (ValueError, TypeError, UnicodeError):
            raise RegistrarError(
                ReasonCode.JOURNAL_INVALID, operation_id=original_id
            ) from None
    if not isinstance(journal, dict) or set(journal) != _versioned_keys(_JOURNAL_KEYS, journal):
        raise RegistrarError(ReasonCode.JOURNAL_INVALID, operation_id=original_id)
    journal["phase"] = phase
    terminal_config: str | None = secondary_record["config_postimage"]
    terminal_receipt: str | None = secondary_record["receipt_postimage"]
    if cancellation:
        # Cancellation retains only bounded replay evidence. The unused exact
        # staged postimages must not survive under a journal or terminal name.
        terminal_config = _image_digest(_decoded(secondary_record["config_postimage"]))
        terminal_receipt = _image_digest(_decoded(secondary_record["receipt_postimage"]))
        journal.update(
            config_preimage=terminal_config,
            config_postimage=terminal_config,
            receipt_preimage=terminal_receipt,
            receipt_postimage=terminal_receipt,
        )
    final_journal_data = canonical_json_bytes(journal)
    _mutation_guard(registrar, active_prepared._context, active_record, "original_journal", _decoded(active_record["config_postimage"]), _decoded(active_record["receipt_postimage"]), prepared=active_prepared, approval=approval)
    store.replace(journal_path, final_journal_data)
    target_binding = inspect_target(prepared._context.config_path)
    terminal = _terminal_payload(
        operation_id=original_id,
        payload_digest=original["payload_digest"],
        action_digest=original_result.action_digest,
        action=Action(original["action"]),
        result=original_result,
        config_postimage=terminal_config,
        receipt_postimage=terminal_receipt,
        target_binding=target_binding,
        journal_phase=phase,
        journal_data=final_journal_data,
    )
    _mutation_guard(registrar, active_prepared._context, active_record, "original_terminal", _decoded(active_record["config_postimage"]), _decoded(active_record["receipt_postimage"]), prepared=active_prepared, approval=approval)
    store.replace(store.terminal_path(original_id), canonical_json_bytes(terminal))
    if authority_prepared is not None and cancellation:
        _mutation_guard(registrar, active_prepared._context, active_record, "cancel_staging_remove", _decoded(active_record["config_postimage"]), _decoded(active_record["receipt_postimage"]), prepared=active_prepared, approval=approval)
        store.remove(store.prepared_path(original_id))


def _failed_result(
    prepared: PreparedOperation,
    code: ReasonCode,
    *,
    outcome: Outcome,
    config_changed: bool = False,
    state_changed: bool = False,
) -> Result:
    return Result(
        **_result_provenance(prepared._context),
        operation_id=prepared.operation_id,
        action_digest=prepared.action_digest,
        action=prepared.action,
        outcome=outcome,
        config_changed=config_changed,
        state_changed=state_changed,
        verified_postimage=None,
        receipt_id=None,
        recovery_id=prepared.operation_id if outcome is Outcome.RECOVERY_REQUIRED else None,
        reason_codes=(code,),
        conflicts=(code,),
        next_action=(
            "Recover the exact interrupted operation."
            if outcome is Outcome.RECOVERY_REQUIRED
            else "Create a new preview after resolving the reported condition."
        ),
        observations=Observations.with_registered(
            prepared._context, ObservationStatus.UNKNOWN
        ),
    )


def _apply_locked(
    registrar: Any, prepared: PreparedOperation, approval: Approval
) -> Result:
    record, store, binding, completed = preflight_apply(
        registrar, prepared, approval
    )
    if completed is not None:
        return completed
    target_id = record["preview"]["target_id"]
    with store.lock(target_id):
        approval_validated_at = utc_now()
        record, store, binding, completed = preflight_apply(
            registrar,
            prepared,
            approval,
            approval_checked_at=approval_validated_at,
        )
        if completed is not None:
            return completed
        journal_path = store.journal_path(prepared.operation_id)
        journal = _journal_record(
            prepared,
            record,
            phase="prepared",
            approval=approval,
            approval_validated_at=approval_validated_at,
        )
        prepared_journal_data = canonical_json_bytes(journal)
        journal_written = False
        config_replaced = False
        terminal_committed = False
        expected_config = _decoded(record["config_preimage"])
        expected_receipt = _decoded(record["receipt_preimage"])
        def guard(phase: str) -> None:
            _mutation_guard(registrar, prepared._context, record, phase, expected_config, expected_receipt, prepared=prepared, approval=approval)
        try:
            guard("journal_prepared")
            store.write(journal_path, prepared_journal_data)
            journal_written = True
            registrar._fault("journal_prepared")
            config_preimage = _decoded(record["config_preimage"])
            config_postimage = _decoded(record["config_postimage"])
            if config_preimage != config_postimage:
                guard("config_replace")
                atomic_replace_target(binding, config_postimage)
                expected_config = config_postimage
                config_replaced = True
            journal = _journal_record(
                prepared,
                record,
                phase="config_replaced",
                approval=approval,
                approval_validated_at=approval_validated_at,
            )
            guard("journal_" + journal["phase"])
            store.replace(journal_path, canonical_json_bytes(journal))
            registrar._fault("config_replaced")
            current_binding = inspect_target(prepared._context.config_path)
            observed = read_target(current_binding)
            if observed != config_postimage:
                raise RegistrarError(
                    ReasonCode.VERIFICATION_FAILED,
                    target_id=prepared._context.target_id,
                    operation_id=prepared.operation_id,
                )
            if observed is not None:
                registrar._parse_bytes(observed)
            receipt_path = store.receipt_path(target_id)
            receipt_postimage = _decoded(record["receipt_postimage"])
            guard("receipt_replace")
            if receipt_postimage is None:
                store.remove(receipt_path)
            else:
                store.replace(receipt_path, receipt_postimage)
            expected_receipt = receipt_postimage
            journal = _journal_record(
                prepared,
                record,
                phase="verified",
                approval=approval,
                approval_validated_at=approval_validated_at,
            )
            guard("journal_" + journal["phase"])
            store.replace(journal_path, canonical_json_bytes(journal))
            registrar._fault("receipt_verified")
            if prepared.action is Action.UNREGISTER:
                outcome = Outcome.APPLIED if config_replaced else Outcome.NO_CHANGE
                registered = (
                    ObservationStatus.FAIL
                    if receipt_postimage is None
                    else ObservationStatus.PASS
                )
            elif prepared.action is Action.ROLLBACK:
                outcome = Outcome.ROLLED_BACK
                registered = (
                    ObservationStatus.FAIL
                    if receipt_postimage is None
                    else ObservationStatus.PASS
                )
            elif prepared.action is Action.RECOVER:
                outcome = (
                    Outcome.CANCELLED
                    if record.get("recovery_disposition")
                    == RecoveryDisposition.CANCEL.value
                    else Outcome.RECOVERED
                )
                registered = (
                    ObservationStatus.FAIL
                    if receipt_postimage is None
                    else ObservationStatus.PASS
                )
            elif prepared.action is Action.CANCEL:
                outcome = Outcome.CANCELLED
                registered = ObservationStatus.UNKNOWN
            else:
                outcome = (
                    Outcome.APPLIED
                    if config_replaced or record["receipt_preimage"] != record["receipt_postimage"]
                    else Outcome.NO_CHANGE
                )
                registered = ObservationStatus.PASS
            receipt_id = (
                digest_bytes(receipt_postimage) if receipt_postimage is not None else None
            )
            result = Result(
                **_result_provenance(prepared._context),
                operation_id=prepared.operation_id,
                action_digest=prepared.action_digest,
                action=prepared.action,
                outcome=outcome,
                config_changed=config_replaced,
                state_changed=True,
                verified_postimage=_image_digest(config_postimage),
                receipt_id=receipt_id,
                recovery_id=(
                    prepared.operation_id if prepared.action is Action.RECOVER else None
                ),
                reason_codes=(),
                conflicts=(),
                next_action=(
                    "Registration bytes are verified; runtime states remain unknown."
                    if registered is ObservationStatus.PASS
                    else "Registration is absent; runtime states remain unknown."
                ),
                observations=Observations.with_registered(
                    prepared._context, registered
                ),
            )
            _terminalize_original(registrar, store, prepared, record, result, approval)
            if outcome is Outcome.CANCELLED and record.get("original_operation_id"):
                # The original cancellation marker is durable at this point;
                # remove exact unused staging before terminalizing this action.
                guard("cancel_staging_remove")
                store.remove(
                    store.prepared_path(record["original_operation_id"])
                )
            journal = _journal_record(
                prepared,
                record,
                phase="committed",
                approval=approval,
                approval_validated_at=approval_validated_at,
            )
            committed_journal_data = canonical_json_bytes(journal)
            guard("journal_committed")
            store.replace(journal_path, committed_journal_data)
            terminal_binding = inspect_target(prepared._context.config_path)
            guard("terminal_commit")
            store.write(
                store.terminal_path(prepared.operation_id),
                canonical_json_bytes(
                    _terminal_record(
                        prepared,
                        result,
                        config_postimage=record["config_postimage"],
                        receipt_postimage=record["receipt_postimage"],
                        target_binding=terminal_binding,
                        journal_phase="committed",
                        journal_data=committed_journal_data,
                    )
                ),
            )
            terminal_committed = True
            registrar._fault("committed")
            return result
        except RegistrarError as error:
            if terminal_committed:
                return result
            if not journal_written:
                try:
                    journal_written = (
                        store.read_optional(journal_path) == prepared_journal_data
                    )
                except RegistrarError:
                    pass
                if not journal_written:
                    raise
            try:
                observed_binding = inspect_target(prepared._context.config_path)
                observed_config = read_target(observed_binding)
                config_replaced = (
                    _decoded(record["config_preimage"])
                    != _decoded(record["config_postimage"])
                    and observed_config == _decoded(record["config_postimage"])
                )
            except RegistrarError:
                pass
            return _failed_result(
                prepared,
                error.code,
                outcome=Outcome.RECOVERY_REQUIRED,
                config_changed=config_replaced,
                state_changed=True,
            )
        except BaseException:
            if terminal_committed:
                return result
            if not journal_written:
                try:
                    journal_written = (
                        store.read_optional(journal_path) == prepared_journal_data
                    )
                except RegistrarError:
                    pass
                if not journal_written:
                    raise RegistrarError(
                        ReasonCode.WRITE_FAILED,
                        target_id=prepared._context.target_id,
                        operation_id=prepared.operation_id,
                    ) from None
            try:
                observed_binding = inspect_target(prepared._context.config_path)
                observed_config = read_target(observed_binding)
                config_replaced = (
                    _decoded(record["config_preimage"])
                    != _decoded(record["config_postimage"])
                    and observed_config == _decoded(record["config_postimage"])
                )
            except RegistrarError:
                pass
            return _failed_result(
                prepared,
                ReasonCode.WRITE_FAILED,
                outcome=Outcome.RECOVERY_REQUIRED,
                config_changed=config_replaced,
                state_changed=True,
            )


def apply(registrar: Any, prepared: PreparedOperation, approval: Approval) -> Result:
    try:
        return _apply_locked(registrar, prepared, approval)
    except RegistrarError as error:
        if error.code is not ReasonCode.WRITER_RELEASE_FAILED:
            raise
        config_changed = False
        state_changed = False
        try:
            record, store = _load_prepared(prepared, maintenance_validator=_validator(registrar))
            terminal, _binding = _read_valid_terminal(prepared, record, store)
            terminal_result = terminal["result"]
            config_changed = terminal_result["config_changed"]
            state_changed = terminal_result["state_changed"]
        except RegistrarError:
            pass
        return _failed_result(
            prepared,
            ReasonCode.WRITER_RELEASE_FAILED,
            outcome=Outcome.RECOVERY_REQUIRED,
            config_changed=config_changed,
            state_changed=state_changed,
        )


def preflight_batch(requests: Sequence[BatchPreviewRequest]) -> BatchPreflight:
    previews = tuple(
        request.registrar.preview(
            request.path, request.definition, context=request.context
        )
        for request in requests
    )
    return BatchPreflight(
        previews=previews,
        ready=all(preview.ready for preview in previews),
    )


def preflight_apply_batch(requests: Sequence[BatchApplyRequest]) -> None:
    seen_targets: set[str] = set()
    for request in requests:
        target_id = request.context.target_id
        if target_id in seen_targets:
            raise RegistrarError(ReasonCode.OWNER_CONFLICT, target_id=target_id)
        seen_targets.add(target_id)
        preflight_apply(
            request.registrar,
            request.prepared,
            request.approval,
            path=request.path,
            definition=request.definition,
            context=request.context,
            intended_action=request.action,
        )


def apply_batch(requests: Sequence[BatchApplyRequest]) -> tuple[Result, ...]:
    preflight_apply_batch(requests)
    results: list[Result] = []
    stopped = False
    for request in requests:
        if stopped:
            results.append(
                _failed_result(
                    request.prepared,
                    ReasonCode.BATCH_NOT_STARTED,
                    outcome=Outcome.FAILED,
                )
            )
            continue
        try:
            result = request.registrar.apply(request.prepared, request.approval)
        except RegistrarError as error:
            result = _failed_result(
                request.prepared,
                error.code,
                outcome=Outcome.FAILED,
            )
        results.append(result)
        if result.outcome in {
            Outcome.FAILED,
            Outcome.CONFLICT,
            Outcome.UNSUPPORTED,
            Outcome.RECOVERY_REQUIRED,
        }:
            stopped = True
    return tuple(results)


def _revalidate_original_authority(
    store: StateStore, secondary: Mapping[str, Any]
) -> None:
    original_id = secondary.get("original_operation_id")
    if not isinstance(original_id, str):
        return
    original = _load_record_by_id(store, original_id)
    _lineage(store.context, original)
    reference, journal_data = _bind_original_authority(store, original)
    preview = secondary.get("preview")
    if (
        not isinstance(preview, dict)
        or preview.get("private_recovery_reference") != reference
        or preview.get("journal_preimage") != _image_digest(journal_data)
    ):
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            target_id=secondary.get("preview", {}).get("target_id"),
            operation_id=secondary.get("operation_id"),
        )
    if (
        secondary.get("action") == Action.RECOVER.value
        and secondary.get("recovery_disposition")
        == RecoveryDisposition.COMPLETE.value
    ):
        target_id = original["preview"]["target_id"]
        _binding, current_config, current_receipt = _current_pair(
            store.context, store, target_id
        )
        if (
            current_config == _decoded(original["config_preimage"])
            and current_receipt == _decoded(original["receipt_preimage"])
        ):
            journal = _load_original_journal(store, original)
            original_prepared = _prepared_from_record(original, store.context)
            approval = _recorded_approval(
                original_prepared, journal.get("approval")
            )
            if store.context.maintenance_evidence is None:
                _validate_approval(original_prepared, approval)


_RECOVERY_AUTHORITY_FAILURES = frozenset(
    {
        ReasonCode.JOURNAL_INVALID,
        ReasonCode.PREIMAGE_CHANGED,
        ReasonCode.PREPARED_RECORD_REQUIRED,
        ReasonCode.STATE_INVALID,
        ReasonCode.TARGET_CHANGED,
    }
)


def _raise_recovery_authority_failure(
    error: RegistrarError,
    *,
    operation_id: str,
) -> NoReturn:
    """Give invalid durable recovery rows their table-level primary reason."""

    if error.code is ReasonCode.RECOVERY_CONFLICT:
        raise error
    if error.code in _RECOVERY_AUTHORITY_FAILURES:
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            reason_codes=error.reason_codes,
            target_id=error.target_id,
            operation_id=error.operation_id or operation_id,
        ) from None
    raise error


def prepare_recovery(
    registrar: Any,
    original_prepared: PreparedOperation,
    disposition: RecoveryDisposition,
    *,
    context: RegistrationContext | None = None,
) -> PreparedOperation:
    disposition = RecoveryDisposition(disposition)
    active_context = context or original_prepared._context
    original, store = _load_prepared(
        original_prepared, access_context=context, maintenance_validator=_validator(registrar)
    )
    try:
        return _prepare_recovery_loaded(
            registrar,
            original_prepared,
            disposition,
            active_context=active_context,
            original=original,
            store=store,
        )
    except RegistrarError as error:
        _raise_recovery_authority_failure(
            error, operation_id=original_prepared.operation_id
        )


def _prepare_recovery_loaded(
    registrar: Any,
    original_prepared: PreparedOperation,
    disposition: RecoveryDisposition,
    *,
    active_context: RegistrationContext,
    original: Mapping[str, Any],
    store: StateStore,
) -> PreparedOperation:
    target_id = original["preview"]["target_id"]
    validate_target_operation_admission(
        active_context,
        target_id,
        action=Action.RECOVER,
        original_operation_id=original_prepared.operation_id,
        store=store,
    )
    journal = _load_original_journal(store, original)
    recovery_reference, journal_data = _bind_original_authority(store, original)
    binding, current_config, current_receipt = _current_pair(
        active_context, store, target_id
    )
    c0 = _decoded(original["config_preimage"])
    c1 = _decoded(original["config_postimage"])
    r0 = _decoded(original["receipt_preimage"])
    r1 = _decoded(original["receipt_postimage"])
    terminal = store.read_optional(
        store.terminal_path(original_prepared.operation_id)
    )
    conflicts: list[ReasonCode] = []
    if terminal is not None or journal["phase"] in {"cancelled", "rolled_back"}:
        conflicts.append(ReasonCode.RECOVERY_CONFLICT)
    elif disposition is RecoveryDisposition.COMPLETE:
        if current_config == c0 and current_receipt == r0:
            recorded = _recorded_approval(
                original_prepared, journal.get("approval")
            )
            if active_context.maintenance_evidence is None:
                _validate_approval(original_prepared, recorded)
        if not (
            (current_config == c0 and current_receipt == r0)
            or (current_config == c1 and current_receipt == r0)
            or (current_config == c1 and current_receipt == r1)
        ):
            conflicts.append(ReasonCode.RECOVERY_CONFLICT)
        desired_config, desired_receipt = c1, r1
    else:
        if not (current_config == c0 and current_receipt == r0):
            conflicts.append(ReasonCode.RECOVERY_CONFLICT)
        desired_config, desired_receipt = c0, r0
    preview = build_preview(
        action=Action.RECOVER,
        registrar=registrar,
        definition=original_prepared._definition,
        context=active_context,
        binding=binding,
        config_preimage=current_config,
        config_postimage=desired_config,
        receipt_preimage=current_receipt,
        receipt_postimage=desired_receipt,
        owned_actions=(),
        preserved_paths=(),
        conflicts=conflicts,
        original_operation_id=original_prepared.operation_id,
        recovery_disposition=disposition,
        journal_preimage=journal_data,
        private_recovery_reference=recovery_reference,
    )
    return prepare(preview, registrar=registrar)


def prepare_cancel(
    registrar: Any,
    original_prepared: PreparedOperation,
    *,
    context: RegistrationContext | None = None,
) -> PreparedOperation:
    active_context = context or original_prepared._context
    original, store = _load_prepared(
        original_prepared, access_context=context, maintenance_validator=_validator(registrar)
    )
    target_id = original["preview"]["target_id"]
    validate_target_operation_admission(
        active_context,
        target_id,
        action=Action.CANCEL,
        original_operation_id=original_prepared.operation_id,
        store=store,
    )
    if (
        store.read_optional(store.journal_path(original_prepared.operation_id))
        is not None
        or store.read_optional(store.terminal_path(original_prepared.operation_id))
        is not None
    ):
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            operation_id=original_prepared.operation_id,
        )
    recovery_reference, journal_data = _bind_original_authority(store, original)
    binding, current_config, current_receipt = _current_pair(
        active_context, store, target_id
    )
    if (
        current_config != _decoded(original["config_preimage"])
        or current_receipt != _decoded(original["receipt_preimage"])
    ):
        raise RegistrarError(
            ReasonCode.PREIMAGE_CHANGED,
            operation_id=original_prepared.operation_id,
        )
    preview = build_preview(
        action=Action.CANCEL,
        registrar=registrar,
        definition=original_prepared._definition,
        context=active_context,
        binding=binding,
        config_preimage=current_config,
        config_postimage=current_config,
        receipt_preimage=current_receipt,
        receipt_postimage=current_receipt,
        owned_actions=(),
        preserved_paths=(),
        conflicts=(),
        original_operation_id=original_prepared.operation_id,
        journal_preimage=journal_data,
        private_recovery_reference=recovery_reference,
    )
    return prepare(preview, registrar=registrar)


def recover(
    registrar: Any,
    prepared: PreparedOperation,
    disposition: RecoveryDisposition,
    approval: Approval,
) -> Result:
    disposition = RecoveryDisposition(disposition)
    if prepared.action is not Action.RECOVER:
        _validate_approval(prepared, approval, maintenance_validator=_validator(registrar))
        try:
            record, store = _load_prepared(prepared, maintenance_validator=_validator(registrar))
        except RegistrarError as error:
            if error.code is not ReasonCode.PREPARED_RECORD_REQUIRED:
                raise
            try:
                validate_writer_window(prepared._context, maintenance_validator=_validator(registrar))
                store = StateStore(prepared._context)
                terminal, _binding = _read_valid_terminal(prepared, None, store)
                return _result_from_terminal(
                    prepared, terminal, disposition=disposition
                )
            except RegistrarError as terminal_error:
                _raise_recovery_authority_failure(
                    terminal_error, operation_id=prepared.operation_id
                )
        try:
            validate_target_operation_admission(
                prepared._context,
                record["preview"]["target_id"],
                action=prepared.action,
                original_operation_id=record["original_operation_id"],
                store=store,
            )
            terminal, _binding = _read_valid_terminal(prepared, record, store)
            return _result_from_terminal(
                prepared, terminal, disposition=disposition
            )
        except RegistrarError as error:
            _raise_recovery_authority_failure(
                error, operation_id=prepared.operation_id
            )
    record, _store = _load_prepared(prepared, maintenance_validator=_validator(registrar))
    if record.get("recovery_disposition") != disposition.value:
        raise RegistrarError(
            ReasonCode.APPROVAL_INVALID, operation_id=prepared.operation_id
        )
    try:
        return apply(registrar, prepared, approval)
    except RegistrarError as error:
        _raise_recovery_authority_failure(
            error, operation_id=prepared.operation_id
        )


def _definition_record_origin_digest(definition: Any) -> str:
    try:
        transport = definition["transport"]
        if transport["kind"] == "stdio":
            origin = {
                "transport": "stdio",
                "command": transport["command"],
            }
        elif transport["kind"] == "streamable-http":
            origin = {
                "transport": "streamable-http",
                "url": transport["url"],
            }
        else:
            raise ValueError("unknown transport")
        return digest_value(origin)
    except (KeyError, TypeError, ValueError):
        raise RegistrarError(ReasonCode.STATE_INVALID) from None


def _receipt_origin_digest(store: StateStore, snapshot: Mapping[str, Any]) -> str:
    receipt = snapshot["receipt"]
    if not isinstance(receipt, dict):
        raise RegistrarError(ReasonCode.STATE_INVALID)
    record = _load_record_by_id(store, receipt["operation_id"])
    return _definition_record_origin_digest(record["definition"])


def _rollback_owned_actions(
    current: Mapping[str, Any], desired: Mapping[str, Any]
) -> tuple[OwnedLeafAction, ...]:
    current_paths = {**current["source"], **current["auth"]}
    desired_paths = {**desired["source"], **desired["auth"]}
    actions: list[OwnedLeafAction] = []
    for path in sorted(set(current_paths) | set(desired_paths)):
        if path not in desired_paths:
            action = "remove"
        elif path not in current_paths:
            action = "add"
        elif current_paths[path] == desired_paths[path]:
            action = "retain"
        else:
            action = "replace"
        actions.append(OwnedLeafAction(path, action))
    return tuple(actions)


def _validate_rollback_auth_decision(
    context: RegistrationContext,
    store: StateStore,
    current: Mapping[str, Any],
    desired: Mapping[str, Any],
) -> None:
    current_identity = (
        current["auth"],
        current["auth_binding_digest"],
    )
    desired_identity = (
        desired["auth"],
        desired["auth_binding_digest"],
    )
    if current_identity == desired_identity:
        return
    binding = context.auth_binding
    if desired["auth"]:
        if binding is None or binding.digest != desired["auth_binding_digest"]:
            raise RegistrarError(
                ReasonCode.AUTH_BINDING_CONFLICT, target_id=context.target_id
            )
        return
    if current["auth"] and (
        binding is None
        or binding.kind is not AuthKind.NONE
        or binding.target_origin_digest != _receipt_origin_digest(store, current)
    ):
        raise RegistrarError(
            ReasonCode.AUTH_BINDING_CONFLICT, target_id=context.target_id
        )


def rollback(
    registrar: Any,
    operation_ref: OperationRef,
    *,
    context: RegistrationContext,
) -> Preview:
    validate_writer_window(context, maintenance_validator=_validator(registrar))
    if operation_ref._state_directory.absolute() != context.state_directory.absolute():
        raise RegistrarError(ReasonCode.TARGET_CHANGED, target_id=context.target_id)
    store = StateStore(context)
    original = _load_record_by_id(store, operation_ref.operation_id)
    _lineage(context, original)
    try:
        original_action = Action(original["action"])
    except (KeyError, TypeError, ValueError):
        raise RegistrarError(
            ReasonCode.STATE_INVALID,
            target_id=context.target_id,
            operation_id=operation_ref.operation_id,
        ) from None
    if original_action in _SECONDARY_ACTIONS:
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            target_id=context.target_id,
            operation_id=operation_ref.operation_id,
        )
    original_context = original.get("context")
    original_definition = original.get("definition")
    if (
        not isinstance(original_context, dict)
        or any(
            original_context.get(key) != getattr(context, key)
            for key in (
                "source_owner",
                "connection_id",
                "host",
                "surface",
                "scope",
                "mapping_version",
                "mapping_digest",
            )
        )
        or original_context.get("config_path") != str(context.config_path)
        or original_context.get("state_directory") != str(context.state_directory)
        or (
            isinstance(original_definition, dict)
            and (
                original_definition.get("source_owner") != context.source_owner
                or original_definition.get("connection_id") != context.connection_id
            )
        )
    ):
        raise RegistrarError(
            ReasonCode.OWNER_CONFLICT,
            target_id=context.target_id,
            operation_id=operation_ref.operation_id,
        )
    target_id = original["preview"]["target_id"]
    if operation_ref.target_id != target_id:
        raise RegistrarError(ReasonCode.TARGET_CHANGED, target_id=target_id)
    binding, current_config, current_receipt = _current_pair(
        context, store, target_id
    )
    c0 = _decoded(original["config_preimage"])
    c1 = _decoded(original["config_postimage"])
    r0 = _decoded(original["receipt_preimage"])
    r1 = _decoded(original["receipt_postimage"])
    r0_owned = _receipt_owned_snapshot(r0)
    r1_owned = _receipt_owned_snapshot(r1)
    conflicts: list[ReasonCode] = []
    try:
        _validate_rollback_auth_decision(
            context, store, r1_owned, r0_owned
        )
    except RegistrarError as error:
        conflicts.append(error.code)
    if operation_ref.kind is OperationRefKind.COMMITTED_RECEIPT:
        original_prepared = _prepared_from_record(original, context)
        try:
            _terminal, terminal_binding = _read_valid_terminal(
                original_prepared, original, store
            )
        except RegistrarError:
            raise
        if terminal_binding.to_record() != binding.to_record() or not (
            current_config == c1 and current_receipt == r1
        ):
            conflicts.append(ReasonCode.RECOVERY_CONFLICT)
    elif operation_ref.kind is OperationRefKind.PENDING_JOURNAL:
        journal = _load_original_journal(store, original)
        if (
            journal["phase"]
            not in {"prepared", "config_replaced", "verified", "committed"}
            or store.read_optional(
                store.terminal_path(operation_ref.operation_id)
            )
            is not None
        ):
            raise RegistrarError(
                ReasonCode.RECOVERY_CONFLICT,
                target_id=target_id,
                operation_id=operation_ref.operation_id,
            )
        if c0 == c1:
            valid_pending_pair = (
                r0 != r1
                and current_config == c1
                and current_receipt == r1
            )
        else:
            valid_pending_pair = (
                current_config == c1 and current_receipt in {r0, r1}
            )
        if not valid_pending_pair:
            conflicts.append(ReasonCode.RECOVERY_CONFLICT)
    else:
        conflicts.append(ReasonCode.RECOVERY_CONFLICT)
    recovery_reference, journal_data = _bind_original_authority(store, original)
    return build_preview(
        action=Action.ROLLBACK,
        registrar=registrar,
        definition=None,
        context=context,
        binding=binding,
        config_preimage=current_config,
        config_postimage=c0,
        receipt_preimage=current_receipt,
        receipt_postimage=r0,
        owned_actions=_rollback_owned_actions(r1_owned, r0_owned),
        preserved_paths=(),
        conflicts=conflicts,
        original_operation_id=operation_ref.operation_id,
        journal_preimage=journal_data,
        private_recovery_reference=recovery_reference,
    )


def operation_ref(
    prepared: PreparedOperation, *, pending: bool = False, maintenance_validator: Any = None
) -> OperationRef:
    record, store = _load_prepared(prepared, maintenance_validator=maintenance_validator)
    journal = _load_original_journal(store, record)
    journal_data = store.read_optional(store.journal_path(prepared.operation_id))
    if journal_data is None:
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            target_id=prepared.audience.target_id,
            operation_id=prepared.operation_id,
        )
    terminal_data = store.read_optional(
        store.terminal_path(prepared.operation_id)
    )
    terminal_present = terminal_data is not None
    if terminal_data is not None:
        _validate_admission_terminal(
            store=store,
            context=store.context,
            journal=journal,
            journal_data=journal_data,
            terminal_data=terminal_data,
            record=record,
            target_id=record["preview"]["target_id"],
        )
    if (
        not terminal_present
        and journal["phase"]
        in {"prepared", "config_replaced", "verified", "committed"}
    ):
        durable_kind = OperationRefKind.PENDING_JOURNAL
    elif terminal_present and journal["phase"] in {
        "committed",
        "cancelled",
        "rolled_back",
    }:
        durable_kind = OperationRefKind.COMMITTED_RECEIPT
    else:
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            target_id=prepared.audience.target_id,
            operation_id=prepared.operation_id,
        )
    requested_kind = (
        OperationRefKind.PENDING_JOURNAL
        if pending
        else OperationRefKind.COMMITTED_RECEIPT
    )
    if requested_kind is not durable_kind:
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            target_id=prepared.audience.target_id,
            operation_id=prepared.operation_id,
        )
    return OperationRef(
        kind=durable_kind,
        operation_id=prepared.operation_id,
        target_id=record["preview"]["target_id"],
        _state_directory=prepared._state_directory,
    )
