"""Explicit cooperative-maintenance admission; never native exclusion.

No production caller is qualified until its reviewed implementation revision is
bound here. Test doubles are injected by tests, not enrolled by a runtime API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError

from .contracts import (
    Approval, ApprovalAudience, RegistrationContext, bounded_id, digest_value,
    utc_now,
)

VALIDATOR_ID = "dev/int014-maintenance-validator/v1"
APPROVAL_ISSUER = "dev/int014-operation-approval/v1"
QUALIFICATION_ID = "kp-mcp/coordinated-maintenance/v1"
ACCEPTED_CONTRACT_DIGEST = "bb0c2417ae274b5f60717939f9286b8c7acd3d5ff712394d80a8b920e833a7c8"
QUALIFICATION_DIGEST = digest_value({
    "id": QUALIFICATION_ID,
    "validator_id": VALIDATOR_ID,
    "accepted_contract_digest": ACCEPTED_CONTRACT_DIGEST,
    "mechanism": "coordinated-maintenance",
    "concurrency_claim": "coordinated",
})
# Deliberately empty. ADR publication revisions and fixture authority are not
# caller implementation qualification. A reviewed source change must enroll it.
PERMITTED_CALLER_REVISIONS: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MaintenanceValidationRequest:
    """Private in-memory request; never serialized or displayed.

    D2 resolves current lifecycle/writer/consequence evidence and exact approval.
    Before persistence it must establish nonsecret eligibility for *all* durable
    material, including unrelated whole-file bytes. Digests alone cannot do so.
    Expected state is the selected registrar ownership receipt, not a mutable
    digest of the entire directory. Journal mutations have their own closed
    phase records and are checked by the registrar.
    """
    context: RegistrationContext = field(repr=False)
    phase: str
    audience: ApprovalAudience | None
    operation_id: str | None
    action_digest: str | None
    prepared_payload_digest: str | None
    expected_config_digest: str | None
    expected_state_digest: str | None
    original_operation_reference: str | None
    approval: Approval | None = field(repr=False)
    durable_material: tuple[bytes | None, ...] = field(repr=False)
    checked_at: datetime


class MaintenanceValidator(Protocol):
    validator_id: str
    issuer_source_revision: str

    def validate(self, request: MaintenanceValidationRequest) -> None:
        """Raise RegistrarError on unavailable, stale, invalid or unsafe evidence.

        Success means the reviewed dev adapter resolved observations and private
        lifecycle authority. It does not mean unknown writers are excluded.
        """
        ...


def validate_profile(context: RegistrationContext) -> None:
    window = context.writer_window
    evidence = context.maintenance_evidence
    if (
        context.schema != "kp-mcp/registration-context/v2"
        or window is None or evidence is None
        or window.qualification_id != QUALIFICATION_ID
        or window.qualification_digest != QUALIFICATION_DIGEST
        or window.issuer_source_revision not in PERMITTED_CALLER_REVISIONS
        or evidence.accepted_contract_digest != ACCEPTED_CONTRACT_DIGEST
        or window.host != context.host or window.surface != context.surface
        or window.build != context.build or window.mapping_digest != context.mapping_digest
        or window.config_target_id != context.target_id
        or window.state_target_id != bounded_id(str(context.state_directory))
    ):
        raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id)


def validate_runtime(
    context: RegistrationContext,
    validator: MaintenanceValidator | None,
    *,
    phase: str = "admission",
    audience: ApprovalAudience | None = None,
    operation_id: str | None = None,
    action_digest: str | None = None,
    prepared_payload_digest: str | None = None,
    expected_config_digest: str | None = None,
    expected_state_digest: str | None = None,
    original_operation_reference: str | None = None,
    approval: Approval | None = None,
    durable_material: tuple[bytes | None, ...] = (),
    checked_at: datetime | None = None,
) -> None:
    validate_profile(context)
    window = context.writer_window
    evidence = context.maintenance_evidence
    now = checked_at or utc_now()
    if (
        validator is None
        or getattr(validator, "validator_id", None) != VALIDATOR_ID
        or getattr(validator, "issuer_source_revision", None) != window.issuer_source_revision
        or not window.acquired_at <= now <= window.expires_at
        or any(writer.observed_at > now for writer in evidence.known_writers)
        or (audience is not None and digest_value(audience.to_record()) != evidence.audience_digest)
        or (original_operation_reference is not None and evidence.recovery_of != original_operation_reference)
    ):
        raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id)
    request = MaintenanceValidationRequest(
        context, phase, audience, operation_id, action_digest,
        prepared_payload_digest, expected_config_digest, expected_state_digest,
        original_operation_reference, approval, durable_material, now,
    )
    try:
        if validator.validate(request) is not None:
            raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED)
    except RegistrarError:
        raise
    except Exception:
        # Never expose private caller exceptions or treat an unavailable observer
        # as evidence that writers are paused.
        raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id) from None
