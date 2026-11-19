"""Closed durable-state validation for registrar transactions."""

from __future__ import annotations

import base64
from contextvars import ContextVar
from dataclasses import replace, fields
from pathlib import Path
from typing import Any, Mapping

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError

from .contracts import (
    ABSENT_DIGEST,
    ADAPTER_VERSION, RegistrationDefinition, OwnedLeafAction, validate_pointer_set,
    canonical_json_bytes,
    Preview, context_from_record, maintenance_provenance, versioned_schema,
    RESULT_SCHEMA,
    Action,
    Approval,
    ApprovalAudience,
    ObservationStatus,
    Outcome,
    PreparedOperation,
    RecoveryDisposition,
    RegistrationContext,
    digest_bytes,
    digest_value,
    parse_iso,
    strict_json_loads,
)
from .state import StateStore, TargetBinding, inspect_target, read_target


PREPARED_RECORD_SCHEMA = "kp-mcp/prepared-record/v1"
JOURNAL_SCHEMA = "kp-mcp/registrar-journal/v1"
TERMINAL_SCHEMA = "kp-mcp/registrar-terminal/v1"
FIXTURE_ISSUER = "kp-mcp/fixture-isolation/v1"

_RESULT_KEYS = {
    "schema",
    "operation_id",
    "action_digest",
    "action",
    "outcome",
    "config_changed",
    "state_changed",
    "verified_postimage",
    "receipt_id",
    "recovery_id",
    "reason_codes",
    "conflicts",
    "next_action",
    "observations",
}
_OBSERVATION_GROUP_KEYS = {
    "registered",
    "enabled",
    "authenticated",
    "tools_discovered",
    "safe_read",
}
_OBSERVATION_KEYS = {
    "status",
    "timestamp",
    "host",
    "surface",
    "build",
    "connection_revision",
    "evidence_reference",
}
_JOURNAL_KEYS = {
    "schema",
    "operation_id",
    "payload_digest",
    "action_digest",
    "action",
    "phase",
    "target_id",
    "config_preimage",
    "config_postimage",
    "receipt_preimage",
    "receipt_postimage",
    "link_binding",
    "original_operation_id",
    "approval",
    "approval_validated_at",
}
_TARGET_BINDING_KEYS = {
    "logical_path",
    "resolved_path",
    "target_id",
    "existed",
    "leaf_symlink",
    "link_text",
    "target_identity",
    "parent_identities",
    "resolved_parent_identities",
    "mode",
    "uid",
    "gid",
    "flags",
    "xattrs",
}
_TERMINAL_KEYS = {
    "schema",
    "operation_id",
    "payload_digest",
    "action_digest",
    "action",
    "config_postimage",
    "receipt_postimage",
    "target_binding",
    "journal_phase",
    "journal_digest",
    "result",
    "terminal_digest",
}
_PENDING_JOURNAL_PHASES = frozenset(
    {"prepared", "config_replaced", "verified"}
)
_TERMINAL_JOURNAL_PHASES = frozenset(
    {"committed", "cancelled", "rolled_back"}
)
_SECONDARY_ACTIONS = frozenset(
    {Action.RECOVER, Action.ROLLBACK, Action.CANCEL}
)
_PREPARED_KEYS = {
    "schema",
    "record_id",
    "operation_id",
    "action",
    "preview",
    "config_preimage",
    "config_postimage",
    "receipt_preimage",
    "receipt_postimage",
    "context",
    "definition",
    "logical_path",
    "resolved_path",
    "link_binding",
    "original_operation_id",
    "recovery_disposition",
    "expires_at",
    "payload_digest",
}


_PROVENANCE_KEYS = {"concurrency_claim", "writer_window_digest", "maintenance_evidence_digest"}


def _versioned_keys(keys: set[str], record: Mapping[str, Any]) -> set[str]:
    return keys | _PROVENANCE_KEYS if str(record.get("schema", "")).endswith("/v2") else keys


def _valid_version(record: Mapping[str, Any], schema: str) -> bool:
    return record.get("schema") in {schema, schema[:-1] + "2"}


def _check_provenance(
    record: Mapping[str, Any], context: RegistrationContext, schema: str,
    historical: Mapping[str, str] | None = None,
) -> None:
    expected = maintenance_provenance(context) if historical is None else dict(historical)
    if expected:
        if (set(expected) != _PROVENANCE_KEYS or expected["concurrency_claim"] != "coordinated"
            or not _is_digest(expected["writer_window_digest"])
            or not _is_digest(expected["maintenance_evidence_digest"])):
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
    expected_schema = schema[:-1] + "2" if expected else schema
    if record.get("schema") != expected_schema or any(record.get(k) != v for k, v in expected.items()):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
    if not expected and _PROVENANCE_KEYS & set(record):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)


def _validate_v2_prepared(record: Mapping[str, Any]) -> None:
    """Validate nested versions and recompute redundant approval semantics."""
    try:
        record = strict_json_loads(canonical_json_bytes(record))
        context = context_from_record(record["context"])
        is_v2 = context.maintenance_evidence is not None
        _check_provenance(record, context, PREPARED_RECORD_SCHEMA)
        preview = dict(record["preview"])
        keys = {f.name for f in fields(Preview)} - {"_private"}
        if set(preview) != (keys | _PROVENANCE_KEYS if is_v2 else keys):
            raise ValueError("open preview")
        if preview["schema"] != versioned_schema("kp-mcp/registrar-preview/v1", context):
            raise ValueError("mixed preview version")
        if is_v2:
            from .maintenance import validate_profile
            validate_profile(context)
            _check_provenance(preview, context, "kp-mcp/registrar-preview/v1")
        preview_digest = preview.pop("preview_digest")
        if digest_value(preview) != preview_digest:
            raise ValueError("preview hash mismatch")
        # Existing strict operations retain their historical semantic checks;
        # neither an embedded v2 preview nor extra v2 fields can enter that path.
        if not is_v2:
            return
        expected = {
            "definition_digest": context.definition_digest,
            "source_owner": context.source_owner, "source_revision": context.source_revision,
            "connection_id": context.connection_id, "adapter_version": ADAPTER_VERSION,
            "mapping_digest": context.mapping_digest, "host": context.host,
            "surface": context.surface, "build": context.build, "scope": context.scope,
            "target_id": record["link_binding"]["target_id"], "operation_id": record["operation_id"],
            "action": record["action"], "expires_at": record["expires_at"],
            "auth_binding_digest": context.auth_binding.digest if context.auth_binding else "not_applicable",
            "writer_window_digest": context.writer_window.digest,
            "config_changed": record["config_preimage"] != record["config_postimage"],
            "state_changed": record["receipt_preimage"] != record["receipt_postimage"],
        }
        if any(preview[key] != value or type(preview[key]) is not type(value) for key, value in expected.items()):
            raise ValueError("preview contradicts stored operation")
        action = Action(record["action"])
        evidence = context.maintenance_evidence
        if record["definition"] is not None:
            definition = RegistrationDefinition.from_record(record["definition"])
            context.validate_definition(definition)
        elif action in {Action.REGISTER, Action.ADOPT}:
            raise ValueError("source definition missing")
        if action in {Action.UNREGISTER, Action.ROLLBACK} and record["definition"] is not None:
            raise ValueError("unexpected source definition")
        if action in _SECONDARY_ACTIONS:
            from uuid import UUID
            if (str(UUID(record["original_operation_id"])) != record["original_operation_id"]
                or evidence.predecessor_maintenance_id is None or evidence.recovery_of is None
                or (action is Action.RECOVER and record["recovery_disposition"] not in {"complete", "cancel"})
                or (action is not Action.RECOVER and record["recovery_disposition"] is not None)):
                raise ValueError("unbound secondary operation")
        elif (record["original_operation_id"] is not None or record["recovery_disposition"] is not None
              or evidence.predecessor_maintenance_id is not None or evidence.recovery_of is not None
              or preview["private_recovery_reference"] is not None or preview["journal_preimage"] != ABSENT_DIGEST):
            raise ValueError("root operation carries secondary authority")
        if (record["record_id"] != record["operation_id"]
            or record["logical_path"] != str(context.config_path)
            or record["resolved_path"] != record["link_binding"]["resolved_path"]
            or not context.writer_window.acquired_at <= parse_iso(record["expires_at"]) <= context.writer_window.expires_at
            or preview["conflicts"] != []):
            raise ValueError("unbound operation")
        _validate_terminal_target_binding(context, record["link_binding"], target_id=preview["target_id"])
        actions = tuple(OwnedLeafAction(**row) for row in preview["owned_leaf_actions"])
        if actions:
            validate_pointer_set(tuple(row.path for row in actions))
        preserved = preview["preserved_paths"]
        if not isinstance(preserved, list) or preserved != sorted(set(preserved)):
            raise ValueError("invalid preserved pointers")
        for pointer in preserved:
            validate_pointer_set((pointer,))
        audience = ApprovalAudience(context.source_owner, context.connection_id, context.host, context.scope,
                                    preview["target_id"], Action(record["action"]))
        evidence = context.maintenance_evidence
        if (digest_value(audience.to_record()) != evidence.audience_digest
            or evidence.config_preimage_digest != preview["config_preimage"]
            or evidence.state_preimage_digest != preview["receipt_preimage"]
            or evidence.recovery_of != preview["private_recovery_reference"]
            or (record["original_operation_id"] is None) != (evidence.predecessor_maintenance_id is None)):
            raise ValueError("unbound maintenance preview")
        for name in ("config_preimage", "config_postimage", "receipt_preimage", "receipt_postimage"):
            preview_key = {"config_postimage": "desired_config", "receipt_postimage": "desired_receipt"}.get(name, name)
            if _image_digest(_decoded(record[name])) != preview[preview_key]:
                raise ValueError("prepared image mismatch")
        _validate_v2_images(record, context)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RegistrarError(ReasonCode.STATE_INVALID, operation_id=record.get("operation_id")) from None


def _validate_v2_images(record: Mapping[str, Any], context: RegistrationContext, *, registrar: Any = None) -> None:
    """Re-run the source-owned projection, never trust a rehashed desired image."""
    from .claude import ClaudeRegistrar
    from .codex import CodexRegistrar
    from .cursor import CursorRegistrar
    from .transactions import _lineage, _rollback_owned_actions

    action = Action(record["action"])
    preview = record["preview"]
    store = StateStore(context)
    c0, c1, r0, r1 = (_decoded(record[key]) for key in
                      ("config_preimage", "config_postimage", "receipt_preimage", "receipt_postimage"))
    actions: tuple[OwnedLeafAction, ...] = ()
    preserved: tuple[str, ...] = ()
    if action not in _SECONDARY_ACTIONS:
        registrar_type = next((kind for kind in (CursorRegistrar, CodexRegistrar, ClaudeRegistrar)
                               if kind.SURFACE == context.surface), None)
        if registrar_type is None:
            raise ValueError("unsupported projection")
        if registrar is None:
            registrar = registrar_type()
        if context.mapping_digest != registrar.mapping_digest:
            raise ValueError("unsupported mapping")
        receipt, receipt_bytes, receipt_record = registrar._decode_receipt(context, preview["target_id"], r0)
        common = dict(context=context, target_id=preview["target_id"], config_preimage=c0,
                      receipt=receipt, receipt_preimage=receipt_bytes, receipt_record=receipt_record)
        if action is Action.UNREGISTER:
            if receipt is None:
                raise ValueError("unregister requires a receipt-bound native identity")
            expected_config, expected_receipt, actions, conflicts = registrar._plan_unregister(**common)
        else:
            definition = RegistrationDefinition.from_record(record["definition"])
            expected_action, expected_config, expected_receipt, actions, preserved, conflicts = registrar._plan_registration(
                definition, operation_id=record["operation_id"], **common)
            if expected_action is not action:
                raise ValueError("projection action mismatch")
        if conflicts:
            raise ValueError("projection conflict")
    else:
        cancelling = action is Action.CANCEL or (action is Action.RECOVER and record["recovery_disposition"] == "cancel")
        original_id = record["original_operation_id"]
        if store.read_optional(store.prepared_path(original_id)) is None and cancelling:
            # Cancellation intentionally removes the original's staged bytes.
            # Its closed terminal envelope retains the exact resolved pair and
            # child id; normal terminal/admission validation still validates the
            # complete resolver chain before admitting another operation.
            terminal_data = store.read_optional(store.terminal_path(original_id))
            terminal = strict_json_loads(terminal_data) if terminal_data is not None else None
            if (not isinstance(terminal, dict) or set(terminal) != _versioned_keys(_TERMINAL_KEYS, terminal)
                or terminal["schema"] != "kp-mcp/registrar-terminal/v2"
                or terminal["operation_id"] != original_id or terminal["journal_phase"] != "cancelled"
                or terminal["result"]["recovery_id"] != record["operation_id"]
                or terminal["config_postimage"] != _image_digest(c0)
                or terminal["receipt_postimage"] != _image_digest(r0)
                or terminal["terminal_digest"] != digest_value({k: v for k, v in terminal.items() if k != "terminal_digest"})):
                raise ValueError("missing cancellation authority")
            expected_config, expected_receipt = c0, r0
        else:
            original = _load_record_by_id(store, original_id)
            _lineage(context, original)
            if (original["preview"]["target_id"] != preview["target_id"]
                or (action is not Action.ROLLBACK and record["definition"] != original["definition"])):
                raise ValueError("secondary source mismatch")
            before = (_decoded(original["config_preimage"]), _decoded(original["receipt_preimage"]))
            after = (_decoded(original["config_postimage"]), _decoded(original["receipt_postimage"]))
            if cancelling:
                if (c0, r0) != before:
                    raise ValueError("cancellation changed original preimages")
                expected_config, expected_receipt = before
            elif action is Action.RECOVER:
                if (c0, r0) not in (before, (after[0], before[1]), after):
                    raise ValueError("invalid recovery preimages")
                expected_config, expected_receipt = after
            else:
                if Action(original["action"]) in _SECONDARY_ACTIONS or (c0, r0) not in (after, (after[0], before[1])):
                    raise ValueError("invalid rollback preimages")
                expected_config, expected_receipt = before
                actions = _rollback_owned_actions(_receipt_owned_snapshot(after[1]), _receipt_owned_snapshot(before[1]))
    if (c1 != expected_config or r1 != expected_receipt
        or preview["owned_leaf_actions"] != [row.to_dict() for row in actions]
        or preview["preserved_paths"] != list(preserved)):
        raise ValueError("stored image or approval report differs from canonical projection")


def _encoded(value: bytes | None) -> str | None:
    return None if value is None else base64.b64encode(value).decode("ascii")


def _decoded(value: str | None) -> bytes | None:
    return None if value is None else base64.b64decode(value.encode("ascii"), validate=True)


def _image_digest(value: bytes | None) -> str:
    return ABSENT_DIGEST if value is None else digest_bytes(value)


def _recorded_approval(
    prepared: PreparedOperation, value: Any
) -> Approval:
    try:
        if not isinstance(value, dict):
            raise ValueError("missing recorded approval")
        audience_record = value["audience"]
        if not isinstance(audience_record, dict):
            raise ValueError("invalid recorded audience")
        audience = ApprovalAudience(
            source_owner=audience_record["source_owner"],
            connection_id=audience_record["connection_id"],
            host=audience_record["host"],
            scope=audience_record["scope"],
            target_id=audience_record["target_id"],
            action=Action(audience_record["action"]),
        )
        approval = Approval(
            audience=audience,
            operation_id=value["operation_id"],
            action_digest=value["action_digest"],
            prepared_payload_digest=value["prepared_payload_digest"],
            issuer_authority=value["issuer_authority"],
            issuer_reference=value["issuer_reference"],
            issued_at=parse_iso(value["issued_at"]),
            expires_at=parse_iso(value["expires_at"]),
            choice=value["choice"],
            schema=value["schema"],
        )
        if approval.to_dict() != value or (
            approval.audience != prepared.audience
            or approval.operation_id != prepared.operation_id
            or approval.action_digest != prepared.action_digest
            or approval.prepared_payload_digest != prepared.payload_digest
        ):
            raise ValueError("recorded approval does not bind operation")
        return approval
    except (KeyError, TypeError, ValueError):
        raise RegistrarError(
            ReasonCode.JOURNAL_INVALID,
            target_id=prepared.audience.target_id,
            operation_id=prepared.operation_id,
        ) from None


_LOADING_RECORDS: ContextVar[tuple[str, ...]] = ContextVar("registrar_loading_records", default=())


def _load_record_by_id(store: StateStore, operation_id: str) -> dict[str, Any]:
    key = str(store.prepared_path(operation_id))
    chain = _LOADING_RECORDS.get()
    if key in chain:
        raise RegistrarError(ReasonCode.STATE_INVALID, operation_id=operation_id)
    token = _LOADING_RECORDS.set((*chain, key))
    try:
        return _load_record_by_id_inner(store, operation_id)
    finally:
        _LOADING_RECORDS.reset(token)


def _load_record_by_id_inner(store: StateStore, operation_id: str) -> dict[str, Any]:
    data = store.read_optional(store.prepared_path(operation_id))
    if data is None:
        raise RegistrarError(
            ReasonCode.PREPARED_RECORD_REQUIRED, operation_id=operation_id
        )
    try:
        record = strict_json_loads(data)
    except (ValueError, TypeError, UnicodeError):
        raise RegistrarError(
            ReasonCode.STATE_INVALID, operation_id=operation_id
        ) from None
    if not isinstance(record, dict) or set(record) != _versioned_keys(_PREPARED_KEYS, record):
        raise RegistrarError(ReasonCode.STATE_INVALID, operation_id=operation_id)
    supplied = record.pop("payload_digest")
    if (
        not _valid_version(record, PREPARED_RECORD_SCHEMA)
        or record.get("operation_id") != operation_id
        or digest_value(record) != supplied
    ):
        raise RegistrarError(ReasonCode.STATE_INVALID, operation_id=operation_id)
    record["payload_digest"] = supplied
    _validate_v2_prepared(record)
    return record


def _original_action_digest(record: Mapping[str, Any]) -> str:
    return digest_value(
        {
            "payload_digest": record["payload_digest"],
            "redacted_preview": record["preview"],
        }
    )


def _prepared_from_record(
    record: Mapping[str, Any], context: RegistrationContext
) -> PreparedOperation:
    record_context = record.get("context")
    if not isinstance(record_context, dict):
        raise RegistrarError(ReasonCode.STATE_INVALID, operation_id=record.get("operation_id"))
    try:
        action = Action(record["action"])
        original_context = context_from_record(record_context)
        audience = ApprovalAudience(
            source_owner=record_context["source_owner"],
            connection_id=record_context["connection_id"],
            host=record_context["host"],
            scope=record_context["scope"],
            target_id=record["preview"]["target_id"],
            action=action,
        )
        return PreparedOperation(
            schema=versioned_schema("kp-mcp/prepared-operation/v1", original_context),
            record_id=record["record_id"],
            payload_digest=record["payload_digest"],
            operation_id=record["operation_id"],
            action_digest=_original_action_digest(record),
            action=action,
            audience=audience,
            state_changed=False,
            config_changed=False,
            expires_at=parse_iso(record["expires_at"]),
            _state_directory=context.state_directory,
            _context=original_context,
            _definition=None,
        )
    except (KeyError, TypeError, ValueError):
        raise RegistrarError(
            ReasonCode.STATE_INVALID, operation_id=record.get("operation_id")
        ) from None


def _receipt_owned_snapshot(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {
            "source": {},
            "auth": {},
            "auth_binding_digest": "not_applicable",
            "receipt": None,
        }
    try:
        receipt = strict_json_loads(data)
        source = receipt["source_projection"]
        auth = receipt["auth_projection"]
        source_paths = source["paths"]
        auth_paths = auth["paths"]
        if (
            not isinstance(receipt, dict)
            or not isinstance(source, dict)
            or not isinstance(auth, dict)
            or not isinstance(source_paths, dict)
            or not isinstance(auth_paths, dict)
            or set(source_paths) & set(auth_paths)
            or not isinstance(auth["binding_digest"], str)
        ):
            raise ValueError("invalid receipt projection")
        return {
            "source": dict(source_paths),
            "auth": dict(auth_paths),
            "auth_binding_digest": auth["binding_digest"],
            "receipt": receipt,
        }
    except (KeyError, TypeError, ValueError):
        raise RegistrarError(ReasonCode.STATE_INVALID) from None


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_image_digest(value: Any) -> bool:
    return value == ABSENT_DIGEST or _is_digest(value)


def _is_plain_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_identity(value: Any, *, parent: bool) -> bool:
    expected = 3 if parent else 2
    if not isinstance(value, list) or len(value) != expected:
        return False
    offset = 1 if parent else 0
    return (
        (not parent or isinstance(value[0], str))
        and all(_is_plain_int(item) for item in value[offset:])
    )


def _validate_terminal_target_binding(
    context: RegistrationContext,
    value: Any,
    *,
    target_id: str,
) -> None:
    if not isinstance(value, dict) or set(value) != _TARGET_BINDING_KEYS:
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id)
    target_identity = value["target_identity"]
    parent_identities = value["parent_identities"]
    resolved_parent_identities = value["resolved_parent_identities"]
    xattrs = value["xattrs"]
    numeric_or_none = (value["mode"], value["uid"], value["gid"])
    if (
        value["target_id"] != target_id
        or value["logical_path"] != str(context.config_path.absolute())
        or not isinstance(value["resolved_path"], str)
        or not Path(value["resolved_path"]).is_absolute()
        or not isinstance(value["existed"], bool)
        or not isinstance(value["leaf_symlink"], bool)
        or (
            value["link_text"] is not None
            and not isinstance(value["link_text"], str)
        )
        or value["leaf_symlink"] != (value["link_text"] is not None)
        or (
            target_identity is not None
            and not _valid_identity(target_identity, parent=False)
        )
        or not isinstance(parent_identities, list)
        or any(
            not _valid_identity(item, parent=True)
            for item in parent_identities
        )
        or not isinstance(resolved_parent_identities, list)
        or any(
            not _valid_identity(item, parent=True)
            for item in resolved_parent_identities
        )
        or any(
            item is not None and not _is_plain_int(item)
            for item in numeric_or_none
        )
        or not _is_plain_int(value["flags"])
        or not isinstance(xattrs, list)
        or any(
            not isinstance(item, dict)
            or set(item) != {"name", "digest"}
            or not isinstance(item["name"], str)
            or not _is_digest(item["digest"])
            for item in xattrs
        )
        or len({item["name"] for item in xattrs}) != len(xattrs)
        or (
            not value["existed"]
            and any(
                item is not None
                for item in (
                    target_identity,
                    value["mode"],
                    value["uid"],
                    value["gid"],
                )
            )
        )
    ):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id)


def _validate_terminal_result(
    *,
    context: RegistrationContext,
    operation_id: str,
    action_digest: str,
    action: Action,
    result: Any,
    expected_revision: str | None,
    historical_provenance: Mapping[str, str] | None = None,
) -> Outcome:
    if not isinstance(result, dict) or set(result) != _versioned_keys(_RESULT_KEYS, result):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
    _check_provenance(result, context, RESULT_SCHEMA, historical_provenance)
    try:
        result_action = Action(result["action"])
        outcome = Outcome(result["outcome"])
        reason_codes = tuple(ReasonCode(item) for item in result["reason_codes"])
        conflicts = tuple(ReasonCode(item) for item in result["conflicts"])
    except (KeyError, TypeError, ValueError):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id) from None
    if (
        not _valid_version(result, RESULT_SCHEMA)
        or result["operation_id"] != operation_id
        or result["action_digest"] != action_digest
        or result_action is not action
        or not isinstance(result["config_changed"], bool)
        or not isinstance(result["state_changed"], bool)
        or result["state_changed"] is not True
        or not isinstance(result["next_action"], str)
        or not result["next_action"]
        or not isinstance(result["reason_codes"], list)
        or not isinstance(result["conflicts"], list)
        or [item.value for item in reason_codes] != result["reason_codes"]
        or [item.value for item in conflicts] != result["conflicts"]
        or reason_codes
        or conflicts
        or not _is_image_digest(result["verified_postimage"])
        or (result["receipt_id"] is not None and not _is_digest(result["receipt_id"]))
        or (result["recovery_id"] is not None and not isinstance(result["recovery_id"], str))
    ):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
    observations = result["observations"]
    if not isinstance(observations, dict) or set(observations) != _OBSERVATION_GROUP_KEYS:
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
    for item in observations.values():
        if not isinstance(item, dict) or set(item) != _OBSERVATION_KEYS:
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
        try:
            ObservationStatus(item["status"])
            parse_iso(item["timestamp"])
        except (TypeError, ValueError):
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id) from None
        if (
            item["host"] != context.host
            or item["surface"] != context.surface
            or item["build"] != context.build
            or not isinstance(item["connection_revision"], str)
            or (
                expected_revision is not None
                and item["connection_revision"] != expected_revision
            )
            or item["evidence_reference"] is not None
        ):
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
    return outcome


def _validate_terminal_envelope(
    terminal: Any,
    *,
    context: RegistrationContext,
    operation_id: str,
    payload_digest: str,
    action_digest: str,
    action: Action,
    target_id: str,
    expected_revision: str | None,
    store: StateStore,
    resolver_chain: frozenset[str] = frozenset(),
    historical_provenance: Mapping[str, str] | None = None,
) -> Outcome:
    if not isinstance(terminal, dict) or set(terminal) != _versioned_keys(_TERMINAL_KEYS, terminal):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id)
    _check_provenance(terminal, context, TERMINAL_SCHEMA, historical_provenance)
    terminal_payload = dict(terminal)
    supplied_digest = terminal_payload.pop("terminal_digest")
    if (
        not _is_digest(supplied_digest)
        or digest_value(terminal_payload) != supplied_digest
        or not _valid_version(terminal, TERMINAL_SCHEMA)
        or terminal.get("operation_id") != operation_id
        or terminal.get("payload_digest") != payload_digest
        or terminal.get("action_digest") != action_digest
        or terminal.get("action") != action.value
        or terminal.get("journal_phase") not in _TERMINAL_JOURNAL_PHASES
        or not _is_digest(terminal.get("journal_digest"))
    ):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id)
    _validate_terminal_target_binding(
        context, terminal.get("target_binding"), target_id=target_id
    )
    outcome = _validate_terminal_result(
        context=context,
        operation_id=operation_id,
        action_digest=action_digest,
        action=action,
        result=terminal.get("result"),
        expected_revision=expected_revision,
        historical_provenance=historical_provenance,
    )
    phase = terminal["journal_phase"]
    if (
        (phase == "rolled_back" and outcome is not Outcome.ROLLED_BACK)
        or (phase == "cancelled" and outcome is not Outcome.CANCELLED)
        or (
            phase == "committed"
            and outcome
            not in {
                Outcome.APPLIED,
                Outcome.NO_CHANGE,
                Outcome.RECOVERED,
                Outcome.CANCELLED,
                Outcome.ROLLED_BACK,
            }
        )
        or (
            phase == "committed"
            and action is Action.ROLLBACK
            and outcome not in {Outcome.ROLLED_BACK, Outcome.RECOVERED}
        )
        or (
            phase == "committed"
            and action is Action.CANCEL
            and outcome not in {Outcome.CANCELLED, Outcome.RECOVERED}
        )
        or (
            phase == "committed"
            and action is Action.RECOVER
            and outcome not in {Outcome.RECOVERED, Outcome.CANCELLED}
        )
        or (
            phase == "committed"
            and action not in _SECONDARY_ACTIONS
            and outcome
            not in {Outcome.APPLIED, Outcome.NO_CHANGE, Outcome.RECOVERED}
        )
    ):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id)
    recovery_id = terminal["result"]["recovery_id"]
    if outcome is Outcome.RECOVERED or phase in {"rolled_back", "cancelled"}:
        valid_recovery_id = isinstance(recovery_id, str) and bool(recovery_id)
    elif action is Action.RECOVER:
        valid_recovery_id = recovery_id == operation_id
    else:
        valid_recovery_id = recovery_id is None
    if not valid_recovery_id:
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id)
    config_postimage = terminal.get("config_postimage")
    receipt_postimage = terminal.get("receipt_postimage")
    try:
        if phase == "cancelled":
            if not _is_image_digest(config_postimage) or not _is_image_digest(
                receipt_postimage
            ):
                raise ValueError("cancelled terminal requires image digests")
            expected_config_digest = config_postimage
            expected_receipt_id = (
                None if receipt_postimage == ABSENT_DIGEST else receipt_postimage
            )
        else:
            if config_postimage is not None and not isinstance(config_postimage, str):
                raise ValueError("invalid config postimage")
            if receipt_postimage is not None and not isinstance(receipt_postimage, str):
                raise ValueError("invalid receipt postimage")
            expected_config_digest = _image_digest(_decoded(config_postimage))
            receipt_bytes = _decoded(receipt_postimage)
            expected_receipt_id = (
                None if receipt_bytes is None else digest_bytes(receipt_bytes)
            )
    except (AttributeError, TypeError, ValueError):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id) from None
    result = terminal["result"]
    if (
        result["verified_postimage"] != expected_config_digest
        or result["receipt_id"] != expected_receipt_id
    ):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id)
    _validate_terminal_resolver(
        store,
        terminal,
        operation_id=operation_id,
        target_id=target_id,
        resolver_chain=resolver_chain,
    )
    return outcome


def _validate_terminal_resolver(
    store: StateStore,
    terminal: Mapping[str, Any],
    *,
    operation_id: str,
    target_id: str,
    resolver_chain: frozenset[str],
) -> None:
    """Bind a resolved terminal to the exact durable secondary operation."""

    try:
        action = Action(terminal["action"])
        outcome = Outcome(terminal["result"]["outcome"])
        phase = terminal["journal_phase"]
        resolver_id = terminal["result"]["recovery_id"]
        requires_resolver = (
            outcome is Outcome.RECOVERED
            or phase in {"rolled_back", "cancelled"}
        )
        if not requires_resolver:
            return
        if not isinstance(resolver_id, str) or not resolver_id:
            raise ValueError("resolved terminal lacks resolver")
        if resolver_id == operation_id:
            if not (
                action is Action.RECOVER
                and phase == "committed"
                and outcome is Outcome.RECOVERED
            ):
                raise ValueError("terminal cannot resolve itself")
            return
        if operation_id in resolver_chain or resolver_id in resolver_chain:
            raise ValueError("cyclic resolver chain")

        resolver = _load_record_by_id(store, resolver_id)
        if terminal["schema"].endswith("/v2") != resolver["schema"].endswith("/v2"):
            raise ValueError("mixed resolver authority modes")
        preview = resolver.get("preview")
        resolver_action = Action(resolver["action"])
        disposition = resolver.get("recovery_disposition")
        if (
            resolver.get("original_operation_id") != operation_id
            or not isinstance(preview, dict)
            or preview.get("target_id") != target_id
        ):
            raise ValueError("resolver does not bind original operation")
        if phase == "rolled_back":
            valid_kind = (
                resolver_action is Action.ROLLBACK
                and disposition is None
            )
        elif phase == "cancelled":
            valid_kind = (
                resolver_action is Action.CANCEL
                and disposition is None
            ) or (
                resolver_action is Action.RECOVER
                and disposition == RecoveryDisposition.CANCEL.value
            )
        else:
            valid_kind = (
                resolver_action is Action.RECOVER
                and disposition == RecoveryDisposition.COMPLETE.value
            )
        if not valid_kind:
            raise ValueError("resolver action does not match terminal outcome")

        if phase == "cancelled":
            expected_config = _image_digest(
                _decoded(resolver["config_postimage"])
            )
            expected_receipt = _image_digest(
                _decoded(resolver["receipt_postimage"])
            )
        else:
            expected_config = resolver["config_postimage"]
            expected_receipt = resolver["receipt_postimage"]
        if (
            terminal["config_postimage"] != expected_config
            or terminal["receipt_postimage"] != expected_receipt
        ):
            raise ValueError("resolver postimages do not match terminal")

        resolver_journal_data = store.read_optional(
            store.journal_path(resolver_id)
        )
        if resolver_journal_data is None:
            raise ValueError("resolver journal is absent")
        resolver_journal = _load_original_journal(store, resolver)
        if resolver_journal["phase"] not in {"verified", "committed"}:
            raise ValueError("resolver did not reach a resolving phase")

        resolver_terminal_data = store.read_optional(
            store.terminal_path(resolver_id)
        )
        if resolver_terminal_data is not None:
            _validate_admission_terminal(
                store=store,
                context=store.context,
                journal=resolver_journal,
                journal_data=resolver_journal_data,
                terminal_data=resolver_terminal_data,
                record=resolver,
                target_id=target_id,
                _resolver_chain=resolver_chain | {operation_id},
            )
    except (KeyError, TypeError, ValueError, RegistrarError):
        raise RegistrarError(
            ReasonCode.STATE_INVALID,
            target_id=target_id,
            operation_id=operation_id,
        ) from None


def _validate_terminal(
    prepared: PreparedOperation,
    record: Mapping[str, Any] | None,
    store: StateStore,
    terminal: Any,
) -> TargetBinding:
    context = prepared._context
    result_outcome = _validate_terminal_envelope(
        terminal,
        context=context,
        operation_id=prepared.operation_id,
        payload_digest=prepared.payload_digest,
        action_digest=prepared.action_digest,
        action=prepared.action,
        target_id=prepared.audience.target_id,
        expected_revision=context.source_revision,
        store=store,
    )
    if (
        record is not None
        and result_outcome in {Outcome.APPLIED, Outcome.NO_CHANGE}
        and (
            terminal["config_postimage"] != record["config_postimage"]
            or terminal["receipt_postimage"] != record["receipt_postimage"]
            or terminal["journal_phase"] != "committed"
        )
    ):
        raise RegistrarError(ReasonCode.RECOVERY_CONFLICT, target_id=context.target_id)
    binding = inspect_target(context.config_path)
    if binding.to_record() != terminal["target_binding"]:
        raise RegistrarError(ReasonCode.TARGET_CHANGED, target_id=context.target_id)
    target_id = prepared.audience.target_id
    observed_config = read_target(binding)
    observed_receipt = store.read_optional(store.receipt_path(target_id))
    if observed_receipt is not None:
        _receipt_owned_snapshot(observed_receipt)
    if terminal["journal_phase"] == "cancelled":
        if (
            terminal["config_postimage"] != _image_digest(observed_config)
            or terminal["receipt_postimage"] != _image_digest(observed_receipt)
        ):
            raise RegistrarError(ReasonCode.PREIMAGE_CHANGED, target_id=context.target_id)
    else:
        try:
            expected_config = _decoded(terminal["config_postimage"])
            expected_receipt = _decoded(terminal["receipt_postimage"])
        except (AttributeError, TypeError, ValueError):
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id) from None
        if observed_config != expected_config or observed_receipt != expected_receipt:
            raise RegistrarError(ReasonCode.PREIMAGE_CHANGED, target_id=context.target_id)
    journal_data = store.read_optional(store.journal_path(prepared.operation_id))
    if journal_data is None or digest_bytes(journal_data) != terminal["journal_digest"]:
        raise RegistrarError(ReasonCode.RECOVERY_CONFLICT, target_id=context.target_id)
    try:
        journal = strict_json_loads(journal_data)
    except (ValueError, TypeError, UnicodeError):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id) from None
    if (
        not isinstance(journal, dict)
        or set(journal) != _versioned_keys(_JOURNAL_KEYS, journal)
        or not _valid_version(journal, JOURNAL_SCHEMA)
        or journal.get("operation_id") != prepared.operation_id
        or journal.get("payload_digest") != prepared.payload_digest
        or journal.get("action_digest") != prepared.action_digest
        or journal.get("action") != prepared.action.value
        or journal.get("target_id") != prepared.audience.target_id
        or journal.get("phase") != terminal["journal_phase"]
    ):
        raise RegistrarError(ReasonCode.RECOVERY_CONFLICT, target_id=context.target_id)
    if terminal["journal_phase"] == "cancelled" and (
        journal.get("config_preimage") != terminal["config_postimage"]
        or journal.get("config_postimage") != terminal["config_postimage"]
        or journal.get("receipt_preimage") != terminal["receipt_postimage"]
        or journal.get("receipt_postimage") != terminal["receipt_postimage"]
    ):
        raise RegistrarError(ReasonCode.RECOVERY_CONFLICT, target_id=context.target_id)
    _check_provenance(journal, context, JOURNAL_SCHEMA)
    if journal.get("approval") is None:
        if journal.get("phase") != "cancelled":
            raise RegistrarError(
                ReasonCode.JOURNAL_INVALID, target_id=context.target_id
            )
    else:
        _recorded_approval(prepared, journal["approval"])
    return binding


def _read_valid_terminal(
    prepared: PreparedOperation,
    record: Mapping[str, Any] | None,
    store: StateStore,
) -> tuple[dict[str, Any], TargetBinding]:
    data = store.read_optional(store.terminal_path(prepared.operation_id))
    if data is None:
        raise RegistrarError(
            ReasonCode.PREPARED_RECORD_REQUIRED,
            target_id=prepared._context.target_id,
            operation_id=prepared.operation_id,
        )
    try:
        terminal = strict_json_loads(data)
    except (ValueError, TypeError, UnicodeError):
        raise RegistrarError(
            ReasonCode.STATE_INVALID,
            target_id=prepared._context.target_id,
            operation_id=prepared.operation_id,
        ) from None
    binding = _validate_terminal(prepared, record, store, terminal)
    return terminal, binding


def _load_original_journal(
    store: StateStore, original: Mapping[str, Any]
) -> dict[str, Any]:
    operation_id = original["operation_id"]
    data = store.read_optional(store.journal_path(operation_id))
    if data is None:
        raise RegistrarError(
            ReasonCode.JOURNAL_INVALID, operation_id=operation_id
        )
    try:
        journal = strict_json_loads(data)
    except (ValueError, TypeError, UnicodeError):
        raise RegistrarError(
            ReasonCode.JOURNAL_INVALID, operation_id=operation_id
        ) from None
    original_context = context_from_record(original["context"])
    cancelled = isinstance(journal, dict) and journal.get("phase") == "cancelled" and original_context.maintenance_evidence is not None
    expected_images = {
        key: (_image_digest(_decoded(original["config_preimage" if key.startswith("config_") else "receipt_preimage"]))
              if cancelled else original[key])
        for key in ("config_preimage", "config_postimage", "receipt_preimage", "receipt_postimage")
    }
    if (
        not isinstance(journal, dict)
        or set(journal) != _versioned_keys(_JOURNAL_KEYS, journal)
        or not _valid_version(journal, JOURNAL_SCHEMA)
        or journal.get("operation_id") != operation_id
        or journal.get("payload_digest") != original["payload_digest"]
        or journal.get("action_digest") != _original_action_digest(original)
        or journal.get("action") != original["action"]
        or journal.get("target_id") != original["preview"]["target_id"]
        or journal.get("config_preimage") != expected_images["config_preimage"]
        or journal.get("config_postimage") != expected_images["config_postimage"]
        or journal.get("receipt_preimage") != expected_images["receipt_preimage"]
        or journal.get("receipt_postimage") != expected_images["receipt_postimage"]
        or journal.get("link_binding") != original["link_binding"]
        or journal.get("original_operation_id")
        != original["original_operation_id"]
        or journal.get("phase")
        not in {
            "prepared",
            "config_replaced",
            "verified",
            "committed",
            "cancelled",
            "rolled_back",
        }
    ):
        raise RegistrarError(
            ReasonCode.JOURNAL_INVALID, operation_id=operation_id
        )
    original_context = context_from_record(original["context"])
    _check_provenance(journal, original_context, JOURNAL_SCHEMA)
    if journal.get("approval") is None:
        if (
            journal.get("phase") != "cancelled"
            or journal.get("approval_validated_at") is not None
        ):
            raise RegistrarError(
                ReasonCode.JOURNAL_INVALID, operation_id=operation_id
            )
    else:
        prepared = _prepared_from_record(original, store.context)
        approval = _recorded_approval(prepared, journal["approval"])
        try:
            validated_at = parse_iso(journal["approval_validated_at"])
            writer = original["context"]["writer_window"]
            if (
                not isinstance(writer, dict)
                or approval.issuer_authority != ("dev/int014-operation-approval/v1" if original_context.maintenance_evidence else FIXTURE_ISSUER)
                or writer.get("mechanism") != ("coordinated-maintenance" if original_context.maintenance_evidence else "fixture-isolation")
                or approval.issuer_reference
                != writer.get("acquisition_reference")
                or approval.choice != "apply"
                or approval.issued_at < parse_iso(writer["acquired_at"])
                or approval.issued_at > parse_iso(writer["expires_at"])
                or approval.expires_at > prepared.expires_at
                or approval.expires_at > parse_iso(writer["expires_at"])
                or approval.expires_at < approval.issued_at
                or validated_at < approval.issued_at
                or validated_at > approval.expires_at
                or validated_at < parse_iso(writer["acquired_at"])
                or validated_at > parse_iso(writer["expires_at"])
            ):
                raise ValueError("approval was not valid when mutation began")
        except (KeyError, TypeError, ValueError):
            raise RegistrarError(
                ReasonCode.JOURNAL_INVALID, operation_id=operation_id
            ) from None
    return journal


def _validate_admission_terminal(
    *,
    store: StateStore,
    context: RegistrationContext,
    journal: Mapping[str, Any],
    journal_data: bytes,
    terminal_data: bytes,
    record: Mapping[str, Any] | None,
    target_id: str,
    _resolver_chain: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Validate a terminal successor without requiring its historical postimage."""

    try:
        terminal = strict_json_loads(terminal_data)
        if record is None:
            validation_context = context
            operation_id = journal["operation_id"]
            payload_digest = journal["payload_digest"]
            action_digest = journal["action_digest"]
            action = Action(journal["action"])
            expected_revision = None
        else:
            prepared = _prepared_from_record(record, context)
            validation_context = prepared._context
            operation_id = prepared.operation_id
            payload_digest = prepared.payload_digest
            action_digest = prepared.action_digest
            action = prepared.action
            expected_revision = validation_context.source_revision
        result_outcome = _validate_terminal_envelope(
            terminal,
            context=validation_context,
            operation_id=operation_id,
            payload_digest=payload_digest,
            action_digest=action_digest,
            action=action,
            target_id=target_id,
            expected_revision=expected_revision,
            store=store,
            resolver_chain=_resolver_chain,
            historical_provenance=(
                {key: journal[key] for key in _PROVENANCE_KEYS if key in journal}
                if record is None else None
            ),
        )
        if (
            terminal["operation_id"] != journal["operation_id"]
            or terminal["payload_digest"] != journal["payload_digest"]
            or terminal["action_digest"] != journal["action_digest"]
            or terminal["action"] != journal["action"]
            or terminal["journal_phase"] != journal["phase"]
            or terminal["journal_digest"] != digest_bytes(journal_data)
        ):
            raise ValueError("terminal does not bind its journal")
        if record is None:
            if journal["phase"] != "cancelled":
                raise ValueError("terminal operation lost its prepared record")
        else:
            if (
                terminal["payload_digest"] != record["payload_digest"]
                or terminal["action_digest"] != _original_action_digest(record)
                or terminal["action"] != record["action"]
            ):
                raise ValueError("terminal does not bind its prepared record")
            if result_outcome in {Outcome.APPLIED, Outcome.NO_CHANGE} and (
                terminal["config_postimage"] != record["config_postimage"]
                or terminal["receipt_postimage"] != record["receipt_postimage"]
                or terminal["journal_phase"] != "committed"
            ):
                raise ValueError("terminal postimages do not match preparation")
        if journal["phase"] == "cancelled" and (
            journal["config_preimage"] != terminal["config_postimage"]
            or journal["config_postimage"] != terminal["config_postimage"]
            or journal["receipt_preimage"] != terminal["receipt_postimage"]
            or journal["receipt_postimage"] != terminal["receipt_postimage"]
        ):
            raise ValueError("cancelled marker retained staged output")
        return terminal
    except (KeyError, TypeError, ValueError):
        raise RegistrarError(
            ReasonCode.STATE_INVALID,
            target_id=target_id,
            operation_id=journal.get("operation_id"),
        ) from None


def _partial_resolution_child(
    store: StateStore, original: Mapping[str, Any], journal: Mapping[str, Any],
    terminal_data: bytes | None,
) -> str | None:
    """Recognize only an exact interrupted predecessor finalization.

    Reconstruct the *prior* journal from the child's approved digest, then bind
    the full original-authority snapshot. A terminal-looking standalone row is
    never made recoverable merely because it lacks a terminal file.
    """
    original_context = context_from_record(original["context"])
    if original_context.maintenance_evidence is None:
        return None
    candidates = []
    for path in store.root.glob("prepared-*.json"):
        raw = store.read_optional(path)
        if raw is None:
            continue
        try:
            row = strict_json_loads(raw)
            if row.get("original_operation_id") != original["operation_id"]:
                continue
            child = _load_record_by_id(store, row["operation_id"])
            child_context = context_from_record(child["context"])
            if (child_context.maintenance_evidence is None
                or child_context.maintenance_evidence.predecessor_maintenance_id != original_context.maintenance_evidence.maintenance_id):
                raise ValueError("invalid child lineage")
            child_journal = _load_original_journal(store, child)
            if child_journal["phase"] != "verified" or store.read_optional(store.terminal_path(child["operation_id"])) is not None:
                continue
            action = Action(child["action"])
            cancellation = action is Action.CANCEL or (action is Action.RECOVER and child["recovery_disposition"] == "cancel")
            expected_phase = "rolled_back" if action is Action.ROLLBACK else "cancelled" if cancellation else "committed"
            if action not in _SECONDARY_ACTIONS or journal["phase"] != expected_phase:
                continue
            if child["preview"]["target_id"] != original["preview"]["target_id"]:
                raise ValueError("foreign child target")
            _binding, config, receipt = _current_pair(store.context, store, child["preview"]["target_id"])
            if config != _decoded(child["config_postimage"]) or receipt != _decoded(child["receipt_postimage"]):
                raise ValueError("child postimage is not current")
            prior_journal = None
            prior_phase = None
            wanted = child["preview"]["journal_preimage"]
            if wanted != ABSENT_DIGEST:
                for phase in _PENDING_JOURNAL_PHASES | _TERMINAL_JOURNAL_PHASES:
                    trial = {**journal, "phase": phase,
                             **{key: original[key] for key in ("config_preimage", "config_postimage", "receipt_preimage", "receipt_postimage")}}
                    encoded = canonical_json_bytes(trial)
                    if digest_bytes(encoded) == wanted:
                        prior_journal, prior_phase = encoded, phase
                        break
                if prior_journal is None:
                    raise ValueError("cannot reconstruct bound predecessor")
            elif action is not Action.CANCEL or journal["approval"] is not None:
                raise ValueError("invalid unstarted cancellation")
            if terminal_data is not None:
                if prior_journal is None:
                    raise ValueError("terminal without prior journal")
                _validate_admission_terminal(store=store, context=original_context,
                    journal=strict_json_loads(prior_journal), journal_data=prior_journal,
                    terminal_data=terminal_data, record=original, target_id=original["preview"]["target_id"])
            snapshot = {
                "original_operation_id": original["operation_id"],
                "target_id": original["preview"]["target_id"],
                "prepared_digest": digest_bytes(store.read_optional(store.prepared_path(original["operation_id"]))),
                "journal_digest": _image_digest(prior_journal),
                "terminal_digest": _image_digest(terminal_data), "journal_phase": prior_phase,
            }
            if digest_value(snapshot) != child["preview"]["private_recovery_reference"]:
                raise ValueError("child does not bind predecessor pretransition state")
            candidates.append(child["operation_id"])
        except (ValueError, TypeError, KeyError, AttributeError):
            raise RegistrarError(ReasonCode.RECOVERY_CONFLICT, operation_id=original["operation_id"]) from None
    if len(candidates) > 1:
        raise RegistrarError(ReasonCode.RECOVERY_CONFLICT, operation_id=original["operation_id"])
    return candidates[0] if candidates else None


def _target_unresolved_journals(
    store: StateStore, target_id: str
) -> dict[str, dict[str, Any]]:
    """Return validated unresolved journals for one canonical target."""

    try:
        candidates = tuple(store.root.iterdir())
    except OSError:
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id) from None
    unresolved: dict[str, dict[str, Any]] = {}
    observed_operations: set[str] = set()
    for path in candidates:
        if not path.name.startswith("journal-") or path.suffix != ".json":
            continue
        operation_id = path.name[len("journal-") : -len(".json")]
        if not operation_id or path != store.journal_path(operation_id):
            raise RegistrarError(ReasonCode.JOURNAL_INVALID, target_id=target_id)
        prepared_data = store.read_optional(store.prepared_path(operation_id))
        record: dict[str, Any] | None = None
        if prepared_data is not None:
            record = _load_record_by_id(store, operation_id)
            preview = record.get("preview")
            record_target = (
                preview.get("target_id") if isinstance(preview, dict) else None
            )
            if not isinstance(record_target, str):
                raise RegistrarError(
                    ReasonCode.STATE_INVALID,
                    target_id=target_id,
                    operation_id=operation_id,
                )
            if record_target != target_id:
                continue
        data = store.read_optional(path)
        if data is None:
            continue
        try:
            candidate = strict_json_loads(data)
        except (ValueError, TypeError, UnicodeError):
            raise RegistrarError(ReasonCode.JOURNAL_INVALID, target_id=target_id) from None
        if not isinstance(candidate, dict):
            raise RegistrarError(ReasonCode.JOURNAL_INVALID, target_id=target_id)
        if record is None and candidate.get("target_id") != target_id:
            continue
        if (
            candidate.get("operation_id") != operation_id
            or candidate.get("target_id") != target_id
            or operation_id in observed_operations
        ):
            raise RegistrarError(
                ReasonCode.JOURNAL_INVALID,
                target_id=target_id,
                operation_id=operation_id,
            )
        observed_operations.add(operation_id)
        if record is None:
            journal = candidate
            if (
                set(journal) != _versioned_keys(_JOURNAL_KEYS, journal)
                or not _valid_version(journal, JOURNAL_SCHEMA)
                or journal.get("phase") != "cancelled"
            ):
                raise RegistrarError(
                    ReasonCode.JOURNAL_INVALID,
                    target_id=target_id,
                    operation_id=operation_id,
                )
        else:
            record = _load_record_by_id(store, operation_id)
            journal = _load_original_journal(store, record)
        terminal_data = store.read_optional(store.terminal_path(operation_id))
        if record is not None and journal["phase"] in _TERMINAL_JOURNAL_PHASES:
            terminal_matches = False
            if terminal_data is not None:
                try:
                    terminal_matches = strict_json_loads(terminal_data).get("journal_digest") == digest_bytes(data)
                except (ValueError, TypeError, AttributeError):
                    pass
            if not terminal_matches and _partial_resolution_child(store, record, journal, terminal_data) is not None:
                unresolved[operation_id] = journal
                continue
        if journal["phase"] in _PENDING_JOURNAL_PHASES or (
            journal["phase"] == "committed" and terminal_data is None
        ):
            if terminal_data is not None:
                raise RegistrarError(
                    ReasonCode.RECOVERY_CONFLICT,
                    target_id=target_id,
                    operation_id=operation_id,
                )
            unresolved[operation_id] = journal
        elif journal["phase"] in _TERMINAL_JOURNAL_PHASES:
            if terminal_data is None:
                raise RegistrarError(
                    ReasonCode.RECOVERY_CONFLICT,
                    target_id=target_id,
                    operation_id=operation_id,
                )
            _validate_admission_terminal(
                store=store,
                context=store.context,
                journal=journal,
                journal_data=data,
                terminal_data=terminal_data,
                record=record,
                target_id=target_id,
            )
        else:
            raise RegistrarError(
                ReasonCode.JOURNAL_INVALID,
                target_id=target_id,
                operation_id=operation_id,
            )
    for path in candidates:
        if not path.name.startswith("terminal-") or path.suffix != ".json":
            continue
        data = store.read_optional(path)
        if data is None:
            continue
        try:
            terminal = strict_json_loads(data)
            terminal_target = terminal.get("target_binding", {}).get("target_id")
        except (AttributeError, TypeError, ValueError, UnicodeError):
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=target_id) from None
        if terminal_target != target_id:
            continue
        operation_id = terminal.get("operation_id")
        if (
            not isinstance(operation_id, str)
            or path != store.terminal_path(operation_id)
            or operation_id not in observed_operations
        ):
            raise RegistrarError(
                ReasonCode.STATE_INVALID,
                target_id=target_id,
                operation_id=operation_id if isinstance(operation_id, str) else None,
            )
    return unresolved


def validate_target_operation_admission(
    context: RegistrationContext,
    target_id: str,
    *,
    action: Action | None = None,
    original_operation_id: str | None = None,
    store: StateStore | None = None,
) -> None:
    """Refuse unresolved target operations except their exact secondary lineage."""

    if not context.state_directory.exists():
        return
    active_store = store or StateStore(context)
    unresolved = _target_unresolved_journals(active_store, target_id)
    if not unresolved:
        return
    allowed: set[str] = set()
    if action in _SECONDARY_ACTIONS and original_operation_id:
        operation_id: str | None = original_operation_id
        while operation_id and operation_id in unresolved and operation_id not in allowed:
            allowed.add(operation_id)
            parent = unresolved[operation_id].get("original_operation_id")
            operation_id = parent if isinstance(parent, str) else None
    if set(unresolved) - allowed:
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            target_id=target_id,
            operation_id=next(iter(sorted(set(unresolved) - allowed))),
        )


def _original_authority_snapshot(
    store: StateStore, original: Mapping[str, Any]
) -> tuple[dict[str, Any], bytes | None]:
    operation_id = original["operation_id"]
    target_id = original["preview"]["target_id"]
    prepared_data = store.read_optional(store.prepared_path(operation_id))
    if prepared_data is None:
        raise RegistrarError(
            ReasonCode.PREPARED_RECORD_REQUIRED,
            target_id=target_id,
            operation_id=operation_id,
        )
    loaded = _load_record_by_id(store, operation_id)
    if loaded != original:
        raise RegistrarError(
            ReasonCode.STATE_INVALID,
            target_id=target_id,
            operation_id=operation_id,
        )
    journal_data = store.read_optional(store.journal_path(operation_id))
    terminal_data = store.read_optional(store.terminal_path(operation_id))
    phase: str | None = None
    if journal_data is not None:
        journal = _load_original_journal(store, original)
        phase = journal["phase"]
        if terminal_data is not None:
            _validate_admission_terminal(
                store=store,
                context=store.context,
                journal=journal,
                journal_data=journal_data,
                terminal_data=terminal_data,
                record=original,
                target_id=target_id,
            )
        elif phase in _TERMINAL_JOURNAL_PHASES and phase != "committed":
            raise RegistrarError(
                ReasonCode.RECOVERY_CONFLICT,
                target_id=target_id,
                operation_id=operation_id,
            )
    elif terminal_data is not None:
        raise RegistrarError(
            ReasonCode.RECOVERY_CONFLICT,
            target_id=target_id,
            operation_id=operation_id,
        )
    snapshot = {
        "original_operation_id": operation_id,
        "target_id": target_id,
        "prepared_digest": digest_bytes(prepared_data),
        "journal_digest": _image_digest(journal_data),
        "terminal_digest": _image_digest(terminal_data),
        "journal_phase": phase,
    }
    return snapshot, journal_data


def _bind_original_authority(
    store: StateStore, original: Mapping[str, Any]
) -> tuple[str, bytes | None]:
    snapshot, journal_data = _original_authority_snapshot(store, original)
    return digest_value(snapshot), journal_data


def _current_pair(
    context: RegistrationContext,
    store: StateStore,
    target_id: str,
) -> tuple[TargetBinding, bytes | None, bytes | None]:
    binding = inspect_target(context.config_path)
    if binding.target_id != target_id:
        raise RegistrarError(ReasonCode.TARGET_CHANGED, target_id=target_id)
    receipt = store.read_optional(store.receipt_path(target_id))
    if receipt is not None:
        _receipt_owned_snapshot(receipt)
    return (binding, read_target(binding), receipt)
