"""Bootstrap-local exception hierarchy.

Dependency direction: google-kit → kp-mcp-bootstrap, never the reverse.
Do not import google_kit here.
"""

from __future__ import annotations

from enum import StrEnum


class BootstrapError(Exception):
    """Base exception for kp-mcp-bootstrap failures."""


class SecretStoreError(BootstrapError):
    """Keychain or secret-storage operation failed."""


class OAuthError(BootstrapError):
    """OAuth flow, token-exchange, or token-refresh failure."""


class ConfigError(BootstrapError):
    """Configuration resolution or validation failure."""


class ReasonCode(StrEnum):
    """Closed, non-sensitive registrar failure and result reasons."""

    MALFORMED_CONFIG = "malformed_config"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    UNSUPPORTED_TRANSPORT = "unsupported_transport"
    UNSUPPORTED_FIELD = "unsupported_field"
    OWNERSHIP_UNKNOWN = "ownership_unknown"
    OWNER_CONFLICT = "owner_conflict"
    OWNED_FIELD_DRIFT = "owned_field_drift"
    POLICY_CONFLICT = "policy_conflict"
    REMOVAL_CONFLICT = "removal_conflict"
    AUTH_BINDING_CONFLICT = "auth_binding_conflict"
    PREIMAGE_CHANGED = "preimage_changed"
    TARGET_CHANGED = "target_changed"
    CONCURRENCY_UNQUALIFIED = "concurrency_unqualified"
    PERMISSION_DENIED = "permission_denied"
    BACKUP_FAILED = "backup_failed"
    WRITE_FAILED = "write_failed"
    VERIFICATION_FAILED = "verification_failed"
    JOURNAL_INVALID = "journal_invalid"
    CONTEXT_REQUIRED = "context_required"
    RECOVERY_CONFLICT = "recovery_conflict"
    STALE_PREVIEW = "stale_preview"
    PREPARED_RECORD_REQUIRED = "prepared_record_required"
    APPROVAL_INVALID = "approval_invalid"
    EXISTING_AUTH_MATERIAL = "existing_auth_material"
    WRITER_RELEASE_FAILED = "writer_release_failed"
    STATE_INVALID = "state_invalid"
    BATCH_NOT_STARTED = "batch_not_started"


class RegistrarError(BootstrapError):
    """Bounded registrar error that never includes host values or raw paths."""

    def __init__(
        self,
        code: ReasonCode,
        *,
        reason_codes: tuple[ReasonCode, ...] | None = None,
        target_id: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        self.code = ReasonCode(code)
        supplied = tuple(ReasonCode(item) for item in (reason_codes or (self.code,)))
        self.reason_codes = tuple(dict.fromkeys((self.code, *supplied)))
        self.target_id = target_id
        self.operation_id = operation_id
        parts = [f"registrar:{self.code.value}"]
        if target_id:
            parts.append(f"target={target_id[:16]}")
        if operation_id:
            parts.append(f"operation={operation_id}")
        super().__init__(" ".join(parts))

    def __repr__(self) -> str:
        target = self.target_id[:16] if self.target_id else None
        return (
            "RegistrarError("
            f"code={self.code.value!r}, target_id={target!r}, "
            f"operation_id={self.operation_id!r})"
        )
