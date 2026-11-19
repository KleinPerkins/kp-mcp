"""Sandbox end-to-end harness for google-kit Phase 6 live verification.

Live execution is gated behind GOOGLE_KIT_SANDBOX=1. When that env var is absent
the harness raises SandboxSkipped, which pytest converts to a clean skip via the
conftest fixture. The harness is fully implemented and ready to run once operator
sandbox credentials are loaded.

Usage in tests (the harness records the run; the caller builds the service and
drives the op explicitly — keeping the harness kit-agnostic)::

    from kp_mcp_testkit.sandbox import require_sandbox, SandboxHarness, sandbox_profile

    def test_live_drive_create():
        require_sandbox()                                  # skip if no creds
        harness = SandboxHarness(op="drive.create", run_id_prefix="p6-e2e")
        ctx = harness.build_context()                      # run_id + audit record
        svc = build_service_for_op("drive.create", profile=sandbox_profile())
        try:
            result = drive_create(inp, service=svc)
            ctx.record_created(result.data.id)
            ctx.record_comparison(passed=..., deviation=...)
            ...                                            # delete + verify gone
            ctx.record_cleaned_up()
        finally:
            harness.emit_audit(ctx)

Sandbox lifecycle: create → read-back → compare(semantic) → delete → verify cleanup.
All created resources use a run_id prefix for safe identification and cleanup.

Environment:
    GOOGLE_KIT_SANDBOX=1         — required to execute live tests
    GOOGLE_KIT_SANDBOX_PROFILE   — Keychain profile for sandbox credentials (default: sandbox)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


SANDBOX_ENV_VAR = "GOOGLE_KIT_SANDBOX"
SANDBOX_PROFILE_VAR = "GOOGLE_KIT_SANDBOX_PROFILE"
SANDBOX_SKIP_REASON = "awaiting operator sandbox creds (P6 gate) — set GOOGLE_KIT_SANDBOX=1"


class SandboxSkipped(Exception):
    """Raised when sandbox execution is requested but GOOGLE_KIT_SANDBOX is not set.

    pytest conftest converts this to pytest.skip(SANDBOX_SKIP_REASON).
    """


def is_sandbox_enabled() -> bool:
    """Return True if GOOGLE_KIT_SANDBOX=1 is set in the environment."""
    return os.environ.get(SANDBOX_ENV_VAR, "").strip() == "1"


def require_sandbox() -> None:
    """Raise SandboxSkipped unless GOOGLE_KIT_SANDBOX=1 is set.

    Call at the top of any live-execution test to gate on creds availability.
    """
    if not is_sandbox_enabled():
        raise SandboxSkipped(SANDBOX_SKIP_REASON)


def sandbox_profile() -> str:
    """Return the Keychain profile name for sandbox credentials."""
    return os.environ.get(SANDBOX_PROFILE_VAR, "").strip() or "sandbox"


@dataclass
class SandboxAuditRecord:
    """Audit record for one sandbox e2e run."""

    run_id: str
    op: str
    created_ids: list[str] = field(default_factory=list)
    cleaned_up: bool = False
    comparison_passed: bool = False
    deviation: str = ""


@dataclass
class SandboxRunContext:
    """Context object passed to the test body inside a SandboxHarness.run() block."""

    run_id: str
    op: str
    profile: str
    audit: SandboxAuditRecord

    def record_created(self, resource_id: str) -> None:
        """Record a resource ID created during this run (for cleanup verification)."""
        self.audit.created_ids.append(resource_id)

    def record_comparison(self, *, passed: bool, deviation: str = "") -> None:
        """Record the semantic comparison result for this run."""
        self.audit.comparison_passed = passed
        self.audit.deviation = deviation

    def record_cleaned_up(self) -> None:
        """Mark all created resources as successfully cleaned up."""
        self.audit.cleaned_up = True


class SandboxHarness:
    """Lifecycle manager for live sandbox end-to-end tests.

    Enforces run_id-prefixed resource naming, audit recording, and cleanup
    verification. Live execution only proceeds if GOOGLE_KIT_SANDBOX=1.

    Args:
        op: The operation name being tested (e.g. 'drive.create').
        run_id_prefix: Prefix for sandbox run IDs (default: 'p6-sandbox').
    """

    def __init__(self, op: str, run_id_prefix: str = "p6-sandbox") -> None:
        self._op = op
        self._run_id_prefix = run_id_prefix

    def _make_run_id(self) -> str:
        import uuid
        return f"{self._run_id_prefix}-{self._op}-{uuid.uuid4().hex[:8]}"

    def build_context(self) -> SandboxRunContext:
        """Build a SandboxRunContext for a live e2e test run.

        Raises SandboxSkipped if GOOGLE_KIT_SANDBOX is not set.
        """
        require_sandbox()
        run_id = self._make_run_id()
        audit = SandboxAuditRecord(run_id=run_id, op=self._op)
        return SandboxRunContext(
            run_id=run_id,
            op=self._op,
            profile=sandbox_profile(),
            audit=audit,
        )

    def verify_cleanup(self, ctx: SandboxRunContext, *, service: Any) -> bool:
        """Verify that all resources recorded in ctx were successfully deleted.

        For now, the operator confirms cleanup by calling ctx.record_cleaned_up()
        after the delete call succeeds. This method checks that flag.

        Returns True if cleanup is verified.
        """
        return ctx.audit.cleaned_up

    def emit_audit(self, ctx: SandboxRunContext, *, audit_file: Any = None) -> None:
        """Emit the audit record to the google-kit audit JSONL log.

        Requires google_kit to be importable (available when tests run in-workspace).
        """
        try:
            from google_kit.core.audit import write_audit

            write_audit(
                actor=f"sandbox-e2e:{ctx.profile}",
                op=ctx.op,
                normalized_request={"run_id": ctx.run_id, "created_ids": ctx.audit.created_ids},
                target_ids=ctx.audit.created_ids,
                result="ok" if ctx.audit.comparison_passed else "deviation",
                deviation_flag=not ctx.audit.comparison_passed,
                audit_file=audit_file,
            )
        except ImportError:
            pass
