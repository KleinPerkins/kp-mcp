"""Ownership-aware implementation behind the existing BaseRegistrar name."""

from __future__ import annotations

import base64
import copy
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError

from .maintenance import MaintenanceValidator, validate_runtime

from .contracts import (
    ABSENT_DIGEST,
    ADAPTER_VERSION,
    Action,
    Approval,
    AuthKind,
    Inspection,
    ObservationStatus,
    Observations,
    OperationRef,
    Outcome,
    OwnershipStatus,
    OwnedLeafAction,
    PolicyValidator,
    PreparedOperation,
    Preview,
    RegistrationContext,
    RegistrationDefinition,
    Result,
    SourceIdentity,
    canonical_json_bytes,
    digest_bytes,
    digest_value,
    new_operation_id,
    strict_json_loads,
    validate_hex,
    validate_identifier,
    validate_pointer_set,
)
from .ownership import (
    _ABSENT,
    can_remove_whole_entry,
    get_leaf,
    reconcile_entry,
    semantic_digest,
)
from .state import StateStore, inspect_target, read_target
from .transactions import PREPARED_RECORD_SCHEMA, _PREPARED_KEYS
from .transactions import _load_record_by_id
from .transactions import apply as apply_prepared
from .transactions import build_preview, prepare as prepare_preview
from .transactions import validate_target_operation_admission


class RegistrarV1Base(ABC):
    """One transaction writer for one platform config format."""

    SERVER_NAME = "google-kit"
    SURFACE = "unknown"
    FIXTURE_BUILD = "fixture-v1"
    FIXTURE_CONFIG_NAME = "config"
    ADAPTER_VERSION = ADAPTER_VERSION
    MAPPING_VERSION = "mapping-v1"
    MAPPING_SPEC: Mapping[str, Any] = {}
    SUPPORTED_READ_BUILDS = frozenset({"source-v1", FIXTURE_BUILD})
    PREVIEW_LIFETIME = timedelta(minutes=10)
    RECEIPT_SCHEMA = "kp-mcp/registrar-receipt/v1"

    def __init__(
        self,
        *,
        policy_validator: PolicyValidator | None = None,
        policy_validator_id: str | None = None,
        maintenance_validator: MaintenanceValidator | None = None,
    ) -> None:
        if (policy_validator is None) != (policy_validator_id is None):
            raise ValueError("policy validator and id must be supplied together")
        self._maintenance_validator = maintenance_validator
        self._policy_validator = policy_validator
        self.policy_validator_id = policy_validator_id

    @property
    def mapping_digest(self) -> str:
        return digest_value(
            {
                "adapter_version": self.ADAPTER_VERSION,
                "mapping_version": self.MAPPING_VERSION,
                "surface": self.SURFACE,
                "mapping": self.MAPPING_SPEC,
            }
        )

    def read_only_context(
        self,
        definition: RegistrationDefinition,
        *,
        config_path: Path,
        state_directory: Path,
        host: str,
        surface: str,
        build: str,
        scope: str = "user",
        auth_binding: Any = None,
    ) -> RegistrationContext:
        if build not in self.SUPPORTED_READ_BUILDS or surface != self.SURFACE:
            raise RegistrarError(ReasonCode.UNSUPPORTED_FIELD)
        return RegistrationContext(
            source_owner=definition.source_owner,
            connection_id=definition.connection_id,
            source_revision=definition.source_revision,
            definition_digest=definition.digest,
            host=host,
            surface=surface,
            build=build,
            scope=scope,
            mapping_version=self.MAPPING_VERSION,
            mapping_digest=self.mapping_digest,
            config_path=config_path.absolute(),
            state_directory=state_directory.absolute(),
            auth_binding=auth_binding,
            policy_validator_id=self.policy_validator_id,
        )

    @abstractmethod
    def _empty_data(self) -> Any:
        pass

    @abstractmethod
    def _parse_bytes(self, data: bytes) -> Any:
        pass

    @abstractmethod
    def _serialize_data(self, data: Any) -> bytes:
        pass

    @abstractmethod
    def _get_entry(
        self, data: Any, native_name: str | None = None
    ) -> Mapping[str, Any] | None:
        pass

    @abstractmethod
    def _set_entry(
        self, data: Any, entry: Mapping[str, Any], native_name: str | None = None
    ) -> Any:
        pass

    @abstractmethod
    def _remove_entry(self, data: Any, native_name: str | None = None) -> Any:
        pass

    @abstractmethod
    def _native_projection(
        self,
        definition: RegistrationDefinition,
        context: RegistrationContext,
    ) -> tuple[dict[str, Any], dict[str, Any], frozenset[str]]:
        pass

    def _read(self, path: Path) -> Any:
        if not path.exists():
            return self._empty_data()
        return self._parse_bytes(path.read_bytes())

    def _validate_context(
        self,
        path: Path,
        context: RegistrationContext,
        definition: RegistrationDefinition | None = None,
    ) -> None:
        if path.absolute() != context.config_path.absolute():
            raise RegistrarError(ReasonCode.TARGET_CHANGED, target_id=context.target_id)
        if (
            context.surface != self.SURFACE
            or context.mapping_version != self.MAPPING_VERSION
            or context.mapping_digest != self.mapping_digest
            or context.build not in self.SUPPORTED_READ_BUILDS
            or context.policy_validator_id != self.policy_validator_id
        ):
            raise RegistrarError(ReasonCode.UNSUPPORTED_FIELD, target_id=context.target_id)
        if context.maintenance_evidence is not None:
            validate_runtime(context, self._maintenance_validator, phase="inspection")
        if definition is not None:
            context.validate_definition(definition)

    def _parse_config(self, data: bytes | None) -> Any:
        if data is None or not data.strip():
            return self._empty_data()
        try:
            return self._parse_bytes(data)
        except RegistrarError:
            raise
        except (ValueError, TypeError, UnicodeError):
            raise RegistrarError(ReasonCode.MALFORMED_CONFIG) from None

    def _read_receipt(
        self, context: RegistrationContext, target_id: str
    ) -> tuple[dict[str, Any] | None, bytes | None, dict[str, Any] | None]:
        if not context.state_directory.exists():
            return None, None, None
        store = StateStore(context)
        data = store.read_optional(store.receipt_path(target_id))
        return self._decode_receipt(context, target_id, data)

    def _decode_receipt(
        self, context: RegistrationContext, target_id: str, data: bytes | None,
    ) -> tuple[dict[str, Any] | None, bytes | None, dict[str, Any] | None]:
        """Validate either a live receipt or a durable historical preimage."""
        store = StateStore(context)
        if data is None:
            return None, None, None
        try:
            receipt = strict_json_loads(data)
        except (ValueError, TypeError, UnicodeError):
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=context.target_id
            ) from None
        required = {
            "schema", "receipt_id", "adapter_version", "mapping_digest",
            "source_owner", "connection_id", "source_revision",
            "definition_digest", "native_name", "host", "scope", "target_id",
            "operation_id", "verified_postimage", "source_projection",
            "auth_projection", "previous_receipt_digest",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != required
            or receipt.get("schema") != self.RECEIPT_SCHEMA
        ):
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
        try:
            source = receipt["source_projection"]
            auth = receipt["auth_projection"]
            if (
                not isinstance(source, dict)
                or set(source) != {"owner", "paths"}
                or source["owner"] != receipt["source_owner"]
                or not isinstance(source["paths"], dict)
                or not isinstance(auth, dict)
                or set(auth) != {"owner", "binding_digest", "paths"}
                or not isinstance(auth["paths"], dict)
            ):
                raise ValueError("invalid ownership projection")
            source_paths = tuple(source["paths"])
            auth_paths = tuple(auth["paths"])
            if source_paths:
                validate_pointer_set(source_paths)
            if auth_paths:
                validate_pointer_set(auth_paths)
            if set(source_paths) & set(auth_paths):
                raise ValueError("overlapping ownership projection")
            for digest in (*source["paths"].values(), *auth["paths"].values()):
                validate_hex(digest, allow_absent=True)
            for key in (
                "receipt_id",
                "adapter_version",
                "source_owner",
                "connection_id",
                "source_revision",
                "native_name",
                "host",
                "scope",
                "operation_id",
            ):
                validate_identifier(receipt[key])
            for key in (
                "mapping_digest",
                "definition_digest",
                "target_id",
                "verified_postimage",
                "previous_receipt_digest",
            ):
                validate_hex(receipt[key], allow_absent=key == "previous_receipt_digest")
            if receipt["receipt_id"] != receipt["operation_id"]:
                raise ValueError("receipt identity mismatch")
            if auth_paths:
                validate_identifier(auth["owner"])
                validate_hex(auth["binding_digest"])
            elif (
                auth["owner"] == "not_applicable"
                or auth["binding_digest"] == "not_applicable"
            ):
                if not (
                    auth["owner"] == "not_applicable"
                    and auth["binding_digest"] == "not_applicable"
                ):
                    raise ValueError("partial auth projection identity")
            else:
                validate_identifier(auth["owner"])
                validate_hex(auth["binding_digest"])
        except (AttributeError, KeyError, TypeError, ValueError):
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=context.target_id
            ) from None

        prepared_data = store.read_optional(store.prepared_path(receipt["operation_id"]))
        if prepared_data is None:
            raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
        try:
            prepared_record = _load_record_by_id(store, receipt["operation_id"])
            supplied_digest = prepared_record.pop("payload_digest")
            definition_record = prepared_record["definition"]
            context_record = prepared_record["context"]
            auth_record = context_record.get("auth_binding")
            config_postimage = prepared_record["config_postimage"]
            receipt_preimage = prepared_record["receipt_preimage"]
            receipt_postimage = prepared_record["receipt_postimage"]
            decoded_config = (
                None
                if config_postimage is None
                else base64.b64decode(config_postimage, validate=True)
            )
            decoded_receipt = (
                None
                if receipt_postimage is None
                else base64.b64decode(receipt_postimage, validate=True)
            )
            decoded_previous_receipt = (
                None
                if receipt_preimage is None
                else base64.b64decode(receipt_preimage, validate=True)
            )
            if (
                digest_value(prepared_record) != supplied_digest
                or prepared_record.get("operation_id") != receipt["operation_id"]
                or decoded_receipt != data
                or receipt["previous_receipt_digest"]
                != (
                    ABSENT_DIGEST
                    if decoded_previous_receipt is None
                    else digest_bytes(decoded_previous_receipt)
                )
                or not isinstance(definition_record, dict)
                or digest_value(definition_record) != receipt["definition_digest"]
                or definition_record.get("source_owner") != receipt["source_owner"]
                or definition_record.get("connection_id") != receipt["connection_id"]
                or definition_record.get("source_revision") != receipt["source_revision"]
                or definition_record.get("native_name") != receipt["native_name"]
                or context_record.get("mapping_digest") != receipt["mapping_digest"]
                or context_record.get("host") != receipt["host"]
                or context_record.get("scope") != receipt["scope"]
                or (
                    auth_record is None
                    and (
                        auth["owner"] != "not_applicable"
                        or auth["binding_digest"] != "not_applicable"
                    )
                )
                or (
                    auth_record is not None
                    and (
                        not isinstance(auth_record, dict)
                        or auth["owner"] != auth_record.get("binding_id")
                        or auth["binding_digest"] != digest_value(auth_record)
                    )
                )
                or prepared_record["preview"].get("target_id") != receipt["target_id"]
                or decoded_config is None
                or digest_bytes(decoded_config) != receipt["verified_postimage"]
            ):
                raise ValueError("receipt does not match its prepared operation")
        except (AttributeError, KeyError, TypeError, ValueError):
            raise RegistrarError(
                ReasonCode.STATE_INVALID, target_id=context.target_id
            ) from None
        prepared_record["payload_digest"] = supplied_digest
        return receipt, data, prepared_record

    def _receipt_created_ancestors(
        self,
        context: RegistrationContext,
        receipt: Mapping[str, Any] | None,
        prepared_record: Mapping[str, Any] | None,
    ) -> frozenset[str]:
        if receipt is None or prepared_record is None:
            return frozenset()
        store = StateStore(context)
        created: set[str] = set()
        seen: set[str] = set()
        current_receipt = dict(receipt)
        current_record = dict(prepared_record)
        while True:
            operation_id = current_receipt.get("operation_id")
            if not isinstance(operation_id, str) or operation_id in seen:
                raise RegistrarError(
                    ReasonCode.STATE_INVALID, target_id=context.target_id
                )
            seen.add(operation_id)
            try:
                config_preimage = (
                    None
                    if current_record["config_preimage"] is None
                    else base64.b64decode(
                        current_record["config_preimage"], validate=True
                    )
                )
                config_postimage = (
                    None
                    if current_record["config_postimage"] is None
                    else base64.b64decode(
                        current_record["config_postimage"], validate=True
                    )
                )
                before = self._get_entry(
                    self._parse_config(config_preimage),
                    current_receipt["native_name"],
                ) or {}
                after = self._get_entry(
                    self._parse_config(config_postimage),
                    current_receipt["native_name"],
                ) or {}
                owned_paths = {
                    *current_receipt["source_projection"]["paths"],
                    *current_receipt["auth_projection"]["paths"],
                }
                for path in owned_paths:
                    parts = path.split("/")[1:]
                    for length in range(1, len(parts)):
                        ancestor = "/" + "/".join(parts[:length])
                        if (
                            get_leaf(before, ancestor) is _ABSENT
                            and isinstance(get_leaf(after, ancestor), Mapping)
                        ):
                            created.add(ancestor)
                previous_data = (
                    None
                    if current_record["receipt_preimage"] is None
                    else base64.b64decode(
                        current_record["receipt_preimage"], validate=True
                    )
                )
                expected_previous_digest = (
                    ABSENT_DIGEST
                    if previous_data is None
                    else digest_bytes(previous_data)
                )
                if (
                    current_receipt.get("previous_receipt_digest")
                    != expected_previous_digest
                ):
                    raise ValueError("receipt ancestry digest mismatch")
            except (KeyError, TypeError, ValueError):
                raise RegistrarError(
                    ReasonCode.STATE_INVALID, target_id=context.target_id
                ) from None
            if previous_data is None:
                break
            try:
                previous_receipt = strict_json_loads(previous_data)
                previous_id = previous_receipt["operation_id"]
                if not isinstance(previous_receipt, dict):
                    raise ValueError("invalid previous receipt")
                previous_record = _load_record_by_id(store, previous_id)
                encoded_receipt = previous_record["receipt_postimage"]
                if (
                    encoded_receipt is None
                    or base64.b64decode(encoded_receipt, validate=True)
                    != previous_data
                ):
                    raise ValueError("receipt chain mismatch")
            except (KeyError, TypeError, ValueError):
                raise RegistrarError(
                    ReasonCode.STATE_INVALID, target_id=context.target_id
                ) from None
            current_receipt = previous_receipt
            current_record = previous_record
        return frozenset(created)

    @staticmethod
    def _definition_record_origin_digest(
        definition_record: Mapping[str, Any],
    ) -> str:
        try:
            transport = definition_record["transport"]
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

    def _validate_explicit_auth_removal(
        self,
        context: RegistrationContext,
        receipt: Mapping[str, Any],
        receipt_record: Mapping[str, Any] | None,
    ) -> None:
        if not receipt["auth_projection"]["paths"]:
            return
        binding = context.auth_binding
        if (
            receipt_record is None
            or binding is None
            or binding.kind is not AuthKind.NONE
            or binding.target_origin_digest
            != self._definition_record_origin_digest(receipt_record["definition"])
        ):
            raise RegistrarError(
                ReasonCode.AUTH_BINDING_CONFLICT, target_id=context.target_id
            )

    @staticmethod
    def _receipt_removal_actions(
        receipt: Mapping[str, Any] | None,
    ) -> tuple[OwnedLeafAction, ...]:
        if receipt is None:
            return ()
        paths = {
            *receipt["source_projection"]["paths"],
            *receipt["auth_projection"]["paths"],
        }
        return tuple(OwnedLeafAction(path, "remove") for path in sorted(paths))

    def _receipt_matches_context(
        self,
        receipt: Mapping[str, Any],
        context: RegistrationContext,
        definition: RegistrationDefinition | None,
        target_id: str,
    ) -> bool:
        return (
            receipt.get("adapter_version") == self.ADAPTER_VERSION
            and receipt.get("mapping_digest") == self.mapping_digest
            and receipt.get("source_owner") == context.source_owner
            and receipt.get("connection_id") == context.connection_id
            and receipt.get("host") == context.host
            and receipt.get("scope") == context.scope
            and receipt.get("target_id") == target_id
            and (
                definition is None
                or receipt.get("native_name") == definition.native_name
            )
        )

    def _new_receipt(
        self,
        *,
        operation_id: str,
        definition: RegistrationDefinition,
        context: RegistrationContext,
        target_id: str,
        config_postimage: bytes,
        source_projection: Mapping[str, str],
        auth_projection: Mapping[str, str],
        prior: bytes | None,
    ) -> bytes:
        receipt = {
            "schema": self.RECEIPT_SCHEMA,
            "receipt_id": operation_id,
            "adapter_version": self.ADAPTER_VERSION,
            "mapping_digest": self.mapping_digest,
            "source_owner": definition.source_owner,
            "connection_id": definition.connection_id,
            "source_revision": definition.source_revision,
            "definition_digest": definition.digest,
            "native_name": definition.native_name,
            "host": context.host,
            "scope": context.scope,
            "target_id": target_id,
            "operation_id": operation_id,
            "verified_postimage": digest_bytes(config_postimage),
            "source_projection": {
                "owner": definition.source_owner,
                "paths": dict(source_projection),
            },
            "auth_projection": {
                "owner": (
                    context.auth_binding.binding_id
                    if context.auth_binding
                    else "not_applicable"
                ),
                "binding_digest": (
                    context.auth_binding.digest if context.auth_binding else "not_applicable"
                ),
                "paths": dict(auth_projection),
            },
            "previous_receipt_digest": digest_bytes(prior) if prior else ABSENT_DIGEST,
        }
        return canonical_json_bytes(receipt)

    def _migration_allows(
        self,
        context: RegistrationContext,
        definition: RegistrationDefinition,
        target_id: str,
        config_preimage: bytes | None,
        current: Mapping[str, Any],
        desired_source: Mapping[str, Any],
        desired_auth: Mapping[str, Any],
    ) -> bool:
        evidence = context.migration_evidence
        if evidence is None or config_preimage is None:
            return False
        if (
            evidence.source_owner != definition.source_owner
            or evidence.connection_id != definition.connection_id
            or evidence.source_revision != definition.source_revision
            or evidence.host != context.host
            or evidence.scope != context.scope
            or evidence.native_name != definition.native_name
            or evidence.target_id != target_id
            or evidence.whole_file_digest != digest_bytes(config_preimage)
            or not evidence.retiring_writer_handoff
            or (context.maintenance_evidence is not None and evidence.retiring_writer_handoff != context.maintenance_evidence.maintenance_id)
        ):
            return False
        if set(desired_source) & set(desired_auth):
            return False
        desired_owned = {**desired_source, **desired_auth}
        observed = {
            path: semantic_digest(get_leaf(current, path)) for path in desired_owned
        }
        return observed == dict(evidence.owned_leaf_digests)

    def _policy_code(
        self,
        current: Mapping[str, Any] | None,
        proposed: Mapping[str, Any] | None,
    ) -> ReasonCode | None:
        if self._policy_validator is None:
            return None
        code = self._policy_validator(
            copy.deepcopy(dict(current or {})),
            copy.deepcopy(dict(proposed or {})),
        )
        return None if code is None else ReasonCode(code)

    def _validate_policy_bytes(
        self,
        data: bytes | None,
        definition: RegistrationDefinition | None,
        context: RegistrationContext,
    ) -> None:
        if self._policy_validator is None:
            return
        parsed = self._parse_config(data)
        name = definition.native_name if definition else self.SERVER_NAME
        current = self._get_entry(parsed, name)
        proposed: Mapping[str, Any] = {}
        if definition:
            source, auth, _incompatible = self._native_projection(definition, context)
            proposed = {**source, **auth}
        code = self._policy_code(current, proposed)
        if code is not None:
            raise RegistrarError(code, target_id=context.target_id)

    def preview(
        self,
        path: Path,
        definition: RegistrationDefinition,
        *,
        context: RegistrationContext,
    ) -> Preview:
        self._validate_context(path, context, definition)
        binding = inspect_target(path)
        validate_target_operation_admission(context, binding.target_id)
        config_preimage = read_target(binding)
        receipt, receipt_preimage, receipt_record = self._read_receipt(context, binding.target_id)
        operation_id = new_operation_id()
        action, config_postimage, receipt_postimage, owned_actions, preserved_paths, conflicts = self._plan_registration(
            definition, context=context, target_id=binding.target_id, operation_id=operation_id,
            config_preimage=config_preimage, receipt=receipt, receipt_preimage=receipt_preimage,
            receipt_record=receipt_record,
        )
        return build_preview(
            operation_id=operation_id,
            action=action,
            registrar=self,
            definition=definition,
            context=context,
            binding=binding,
            config_preimage=config_preimage,
            config_postimage=config_postimage,
            receipt_preimage=receipt_preimage,
            receipt_postimage=receipt_postimage,
            owned_actions=owned_actions,
            preserved_paths=preserved_paths,
            conflicts=conflicts,
        )

    def _plan_registration(
        self, definition: RegistrationDefinition, *, context: RegistrationContext,
        target_id: str, operation_id: str, config_preimage: bytes | None,
        receipt: Mapping[str, Any] | None, receipt_preimage: bytes | None,
        receipt_record: Mapping[str, Any] | None,
    ) -> tuple[Any, ...]:
        """One projection path for live previews and historical image verification."""
        data = self._parse_config(config_preimage)
        current = self._get_entry(data, definition.native_name)
        desired_source, desired_auth, incompatible = self._native_projection(
            definition, context
        )
        conflicts: list[ReasonCode] = []
        adoption = False
        if receipt is not None and not self._receipt_matches_context(
            receipt, context, definition, target_id
        ):
            conflicts.append(ReasonCode.OWNER_CONFLICT)
        if current is None and receipt is not None:
            conflicts.append(ReasonCode.OWNED_FIELD_DRIFT)
        if current is not None and receipt is None:
            adoption = self._migration_allows(
                context,
                definition,
                target_id,
                config_preimage,
                current,
                desired_source,
                desired_auth,
            )
            if not adoption:
                conflicts.append(ReasonCode.OWNERSHIP_UNKNOWN)
        if (
            receipt is not None
            and receipt.get("auth_projection", {}).get("paths")
            and context.auth_binding is None
        ):
            conflicts.append(ReasonCode.AUTH_BINDING_CONFLICT)
        merge = reconcile_entry(
            current,
            desired_source,
            desired_auth,
            receipt,
            adoption=adoption,
            incompatible_paths=incompatible,
            prunable_ancestors=self._receipt_created_ancestors(
                context, receipt, receipt_record
            ),
        )
        conflicts.extend(merge.conflicts)
        policy = self._policy_code(current, merge.entry)
        if policy:
            conflicts.append(policy)
        action = Action.ADOPT if adoption else Action.REGISTER
        if conflicts:
            config_postimage = config_preimage
            receipt_postimage = receipt_preimage
        else:
            if current is not None and dict(current) == dict(merge.entry):
                config_postimage = config_preimage
            else:
                updated = copy.deepcopy(data)
                self._set_entry(updated, merge.entry, definition.native_name)
                config_postimage = self._serialize_data(updated)
            auth_digest = (
                context.auth_binding.digest if context.auth_binding else "not_applicable"
            )
            true_noop = bool(
                receipt
                and config_postimage == config_preimage
                and receipt.get("source_revision") == definition.source_revision
                and receipt.get("definition_digest") == definition.digest
                and receipt.get("verified_postimage") == digest_bytes(config_postimage)
                and receipt.get("source_projection", {}).get("paths")
                == dict(merge.source_projection)
                and receipt.get("auth_projection", {}).get("paths")
                == dict(merge.auth_projection)
                and receipt.get("auth_projection", {}).get("binding_digest")
                == auth_digest
            )
            if true_noop:
                receipt_postimage = receipt_preimage
            else:
                receipt_postimage = self._new_receipt(
                    operation_id=operation_id,
                    definition=definition,
                    context=context,
                    target_id=target_id,
                    config_postimage=config_postimage,
                    source_projection=merge.source_projection,
                    auth_projection=merge.auth_projection,
                    prior=receipt_preimage,
                )
        return action, config_postimage, receipt_postimage, merge.actions, merge.preserved_paths, conflicts

    def preview_unregister(
        self, path: Path, *, context: RegistrationContext
    ) -> Preview:
        self._validate_context(path, context)
        binding = inspect_target(path)
        validate_target_operation_admission(context, binding.target_id)
        config_preimage = read_target(binding)
        receipt, receipt_preimage, receipt_record = self._read_receipt(context, binding.target_id)
        config_postimage, receipt_postimage, owned_actions, conflicts = self._plan_unregister(
            context=context, target_id=binding.target_id, config_preimage=config_preimage,
            receipt=receipt, receipt_preimage=receipt_preimage, receipt_record=receipt_record,
        )
        return build_preview(
            action=Action.UNREGISTER,
            registrar=self,
            definition=None,
            context=context,
            binding=binding,
            config_preimage=config_preimage,
            config_postimage=config_postimage,
            receipt_preimage=receipt_preimage,
            receipt_postimage=receipt_postimage,
            owned_actions=owned_actions,
            preserved_paths=(),
            conflicts=conflicts,
        )

    def _plan_unregister(
        self, *, context: RegistrationContext, target_id: str, config_preimage: bytes | None,
        receipt: Mapping[str, Any] | None, receipt_preimage: bytes | None,
        receipt_record: Mapping[str, Any] | None,
    ) -> tuple[Any, ...]:
        data = self._parse_config(config_preimage)
        native_name = receipt.get("native_name") if receipt else self.SERVER_NAME
        current = self._get_entry(data, native_name)
        conflicts: tuple[ReasonCode, ...] = ()
        if receipt is None and (current is not None or context.maintenance_evidence is not None):
            conflicts = (ReasonCode.OWNERSHIP_UNKNOWN,)
        elif receipt is not None and not self._receipt_matches_context(
            receipt, context, None, target_id
        ):
            conflicts = (ReasonCode.OWNER_CONFLICT,)
        elif receipt is not None:
            try:
                self._validate_explicit_auth_removal(
                    context, receipt, receipt_record
                )
            except RegistrarError as error:
                conflicts = (error.code,)
            if not conflicts and current is not None:
                _safe, conflicts = can_remove_whole_entry(current, receipt)
        if conflicts:
            config_postimage = config_preimage
            receipt_postimage = receipt_preimage
        else:
            updated = copy.deepcopy(data)
            if current is not None:
                self._remove_entry(updated, native_name)
                config_postimage = self._serialize_data(updated)
            else:
                config_postimage = config_preimage
            receipt_postimage = None
        return config_postimage, receipt_postimage, self._receipt_removal_actions(receipt), conflicts

    def prepare(self, preview: Preview) -> PreparedOperation:
        return prepare_preview(preview, registrar=self)

    def load_prepared(
        self, record_id: str, *, context: RegistrationContext,
        definition: RegistrationDefinition | None,
    ) -> PreparedOperation:
        from .transactions import load_prepared

        return load_prepared(self, record_id, context=context, definition=definition)

    def apply(self, prepared: PreparedOperation, approval: Approval) -> Result:
        return apply_prepared(self, prepared, approval)

    def inspect_registration(
        self, path: Path, *, context: RegistrationContext
    ) -> Inspection:
        self._validate_context(path, context)
        binding = inspect_target(path)
        validate_target_operation_admission(context, binding.target_id)
        config = read_target(binding)
        data = self._parse_config(config)
        receipt, _receipt_bytes, _receipt_record = self._read_receipt(
            context, binding.target_id
        )
        name = receipt.get("native_name") if receipt else self.SERVER_NAME
        entry = self._get_entry(data, name)
        reasons: list[ReasonCode] = []
        if entry is None:
            ownership = OwnershipStatus.ABSENT
            match: bool | None = False if receipt else None
            status = ObservationStatus.FAIL
            if receipt:
                reasons.append(ReasonCode.OWNED_FIELD_DRIFT)
        elif receipt is None:
            ownership = OwnershipStatus.UNKNOWN
            match = None
            status = ObservationStatus.UNKNOWN
            reasons.append(ReasonCode.OWNERSHIP_UNKNOWN)
        elif not self._receipt_matches_context(
            receipt, context, None, binding.target_id
        ):
            ownership = OwnershipStatus.CONFLICT
            match = False
            status = ObservationStatus.UNKNOWN
            reasons.append(ReasonCode.OWNER_CONFLICT)
        else:
            expected = {
                **receipt["source_projection"]["paths"],
                **receipt["auth_projection"]["paths"],
            }
            match = all(
                semantic_digest(get_leaf(entry, pointer)) == expected_digest
                for pointer, expected_digest in expected.items()
            )
            ownership = OwnershipStatus.OWNED
            status = ObservationStatus.PASS if match else ObservationStatus.UNKNOWN
            if not match:
                reasons.append(ReasonCode.OWNED_FIELD_DRIFT)
        policy = self._policy_code(entry, {})
        if policy:
            reasons.append(policy)
        return Inspection(
            present=entry is not None,
            ownership=ownership,
            owned_projection_match=match,
            reason_codes=tuple(dict.fromkeys(reasons)),
            observations=Observations.with_registered(context, status),
        )

    def current_entry(
        self, config_path: Path, *, context: RegistrationContext | None = None
    ) -> Inspection:
        if context is None:
            raise RegistrarError(ReasonCode.CONTEXT_REQUIRED)
        return self.inspect_registration(config_path, context=context)

    def _legacy_definition(
        self, entry: Any, context: RegistrationContext
    ) -> RegistrationDefinition:
        return RegistrationDefinition.from_server_entry(
            SourceIdentity(
                source_owner=context.source_owner,
                connection_id=context.connection_id,
                source_revision=context.source_revision,
                native_name=self.SERVER_NAME,
            ),
            entry,
        )

    def would_register(
        self,
        config_path: Path,
        entry: Any,
        *,
        context: RegistrationContext | None = None,
    ) -> bool:
        if context is None:
            raise RegistrarError(ReasonCode.CONTEXT_REQUIRED)
        preview = self.preview(
            config_path, self._legacy_definition(entry, context), context=context
        )
        if preview.conflicts:
            raise RegistrarError(
                preview.conflicts[0],
                reason_codes=preview.conflicts,
                target_id=preview.target_id,
            )
        return preview.config_changed or preview.state_changed

    def register(
        self,
        config_path: Path,
        entry: Any,
        *,
        context: RegistrationContext | None = None,
        prepared: PreparedOperation | None = None,
        approval: Approval | None = None,
    ) -> bool:
        if context is None:
            raise RegistrarError(ReasonCode.CONTEXT_REQUIRED)
        definition = self._legacy_definition(entry, context)
        if prepared is None or approval is None:
            preview = self.preview(config_path, definition, context=context)
            if preview.conflicts:
                raise RegistrarError(
                    preview.conflicts[0],
                    reason_codes=preview.conflicts,
                    target_id=preview.target_id,
                )
            if not preview.config_changed and not preview.state_changed:
                return False
            raise RegistrarError(
                ReasonCode.PREPARED_RECORD_REQUIRED, target_id=preview.target_id
            )
        from .transactions import preflight_apply

        preflight_apply(
            self,
            prepared,
            approval,
            path=config_path,
            definition=definition,
            context=context,
            intended_action=Action.REGISTER,
        )
        result = self.apply(prepared, approval)
        self._raise_legacy_failure(result)
        return result.config_changed

    def unregister(
        self,
        config_path: Path,
        *,
        context: RegistrationContext | None = None,
        prepared: PreparedOperation | None = None,
        approval: Approval | None = None,
    ) -> bool:
        if context is None:
            binding = inspect_target(config_path)
            config = read_target(binding)
            if config is None:
                return False
            data = self._parse_config(config)
            if self._get_entry(data, self.SERVER_NAME) is None:
                return False
            raise RegistrarError(ReasonCode.CONTEXT_REQUIRED)
        if prepared is None or approval is None:
            preview = self.preview_unregister(config_path, context=context)
            if preview.conflicts:
                raise RegistrarError(
                    preview.conflicts[0],
                    reason_codes=preview.conflicts,
                    target_id=preview.target_id,
                )
            if not preview.config_changed and not preview.state_changed:
                return False
            raise RegistrarError(
                ReasonCode.PREPARED_RECORD_REQUIRED, target_id=preview.target_id
            )
        from .transactions import preflight_apply

        preflight_apply(
            self,
            prepared,
            approval,
            path=config_path,
            definition=None,
            context=context,
            intended_action=Action.UNREGISTER,
        )
        result = self.apply(prepared, approval)
        self._raise_legacy_failure(result)
        return result.config_changed

    @staticmethod
    def _raise_legacy_failure(result: Result) -> None:
        if result.outcome in {Outcome.APPLIED, Outcome.NO_CHANGE}:
            return
        reason_codes = result.reason_codes or result.conflicts or (
            ReasonCode.WRITE_FAILED,
        )
        raise RegistrarError(
            reason_codes[0],
            reason_codes=reason_codes,
            operation_id=result.operation_id,
        )

    def recover(
        self, prepared: PreparedOperation, disposition: Any, approval: Approval
    ) -> Result:
        from .transactions import recover

        return recover(self, prepared, disposition, approval)

    def prepare_recovery(
        self,
        prepared: PreparedOperation,
        disposition: Any,
        *,
        context: RegistrationContext | None = None,
    ) -> PreparedOperation:
        from .transactions import prepare_recovery

        return prepare_recovery(self, prepared, disposition, context=context)

    def prepare_cancel(
        self,
        prepared: PreparedOperation,
        *,
        context: RegistrationContext | None = None,
    ) -> PreparedOperation:
        from .transactions import prepare_cancel

        return prepare_cancel(self, prepared, context=context)

    def rollback(
        self, operation_ref: OperationRef, *, context: RegistrationContext
    ) -> Preview:
        from .transactions import rollback

        return rollback(self, operation_ref, context=context)

    def _fault(self, _step: str) -> None:
        return
