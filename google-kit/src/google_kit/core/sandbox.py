"""Durable sandbox / debug mode for google-kit (E5).

A safe-playground guardrail: when ``GOOGLE_KIT_SANDBOX=1``, CLI and MCP
operations default to the dedicated *sandbox* Keychain profile instead of the
production default, so a debugging session never accidentally authenticates as —
or mutates data in — the operator's real account. An explicit ``--profile``
(CLI) always wins; when sandbox mode is off the behavior is byte-identical to
before (``profile=None`` falls through to ``GOOGLE_KIT_PROFILE`` / ``default``).

This is the runtime counterpart to the test-only ``kp_mcp_testkit.sandbox``
harness; both honor the same ``GOOGLE_KIT_SANDBOX`` / ``GOOGLE_KIT_SANDBOX_PROFILE``
env contract (testkit stays kit-agnostic and cannot import this module, so the
contract agreement is locked by ``google-kit/tests/test_sandbox_mode.py``).
"""
from __future__ import annotations

import os

SANDBOX_ENV_VAR = "GOOGLE_KIT_SANDBOX"
SANDBOX_PROFILE_VAR = "GOOGLE_KIT_SANDBOX_PROFILE"
DEFAULT_SANDBOX_PROFILE = "sandbox"


def is_sandbox_enabled() -> bool:
    """Return True iff ``GOOGLE_KIT_SANDBOX=1`` (strict — matches the testkit harness)."""
    return os.environ.get(SANDBOX_ENV_VAR, "").strip() == "1"


def sandbox_profile() -> str:
    """Keychain profile used in sandbox mode (``GOOGLE_KIT_SANDBOX_PROFILE`` or ``'sandbox'``)."""
    return os.environ.get(SANDBOX_PROFILE_VAR, "").strip() or DEFAULT_SANDBOX_PROFILE


def resolve_profile(explicit: str | None) -> str | None:
    """Apply the sandbox guardrail to a requested Keychain profile.

    Precedence: an explicit profile always wins; otherwise, in sandbox mode the
    sandbox profile is selected; otherwise ``None`` (the caller's downstream
    default — ``GOOGLE_KIT_PROFILE`` / ``'default'`` — is left untouched).
    """
    if explicit is not None:
        return explicit
    if is_sandbox_enabled():
        return sandbox_profile()
    return None
