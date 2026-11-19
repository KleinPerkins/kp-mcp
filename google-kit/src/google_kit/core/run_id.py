"""Run-ID generation and contextvar propagation for google-kit core (R24).

A run_id is set once per CLI invocation or MCP tool call and propagated
through contextvars so all logs, metrics, and audit records share the same ID.
"""
from __future__ import annotations

import contextvars
import secrets

_RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar("google_kit_run_id", default="")


def new_run_id() -> str:
    """Generate a fresh run ID (16 hex chars = 64 bits of entropy)."""
    return secrets.token_hex(8)


def set_run_id(run_id: str) -> contextvars.Token[str]:
    """Set the current run ID in the contextvar. Returns the reset token."""
    return _RUN_ID.set(run_id)


def get_run_id() -> str:
    """Return the current run ID, or '' if none is set."""
    return _RUN_ID.get()


def ensure_run_id() -> str:
    """Return the current run ID, generating and setting a new one if absent."""
    rid = _RUN_ID.get()
    if not rid:
        rid = new_run_id()
        _RUN_ID.set(rid)
    return rid


def reset_run_id(token: contextvars.Token[str]) -> None:
    """Reset the contextvar to its previous value using the token from set_run_id."""
    _RUN_ID.reset(token)
