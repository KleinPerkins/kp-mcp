"""Error taxonomy for snow-kit core.

Structured MCP/CLI payloads avoid bare tracebacks on the stdio transport.
Snowflake connector exceptions are mapped to a small retry/permission taxonomy.
"""
from __future__ import annotations

import re
from typing import Any

_REDACT_PATTERNS = (
    (re.compile(r"(?i)(password|token|private_key)\s*=\s*\S+"), r"\1=***"),
    (re.compile(r"(?i)Bearer\s+\S+"), "Bearer ***"),
)


class SnowKitError(Exception):
    """Base for all snow-kit errors."""

    def __init__(
        self,
        message: str,
        *,
        op: str = "",
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.op = op
        self.context = context or {}
        self.message = redact_message(message)

    def to_mcp_payload(self) -> dict[str, Any]:
        """Return a structured MCP error payload (no traceback)."""
        return {
            "error": type(self).__name__,
            "message": self.message,
            "op": self.op,
        }


class Transient(SnowKitError):
    """Transient connector/network error; safe to retry once when idempotent."""


class Auth(SnowKitError):
    """Authentication or SSO error; do not retry — reauth required."""


class Timeout(SnowKitError):
    """Tool or statement exceeded a configured timeout."""


class Unavailable(SnowKitError):
    """A configured local or remote source is unavailable; not an empty result."""


class Permission(SnowKitError, PermissionError):
    """Caller lacks permission or the op posture blocks the action."""


class Validation(SnowKitError, ValueError):
    """Input or SQL failed validation; do not retry."""


class Unknown(SnowKitError):
    """Unclassified error; surface to operator without a traceback."""


def redact_message(text: str) -> str:
    """Scrub likely secrets from an error string before MCP/CLI surfacing."""
    out = text
    for pattern, repl in _REDACT_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def classify_connector(exc: Exception, *, op: str = "") -> SnowKitError:
    """Map a Snowflake connector or guard exception to the snow-kit taxonomy."""
    if isinstance(exc, SnowKitError):
        return exc
    if isinstance(exc, TimeoutError):
        return Timeout(str(exc) or "operation timed out", op=op)
    if isinstance(exc, PermissionError):
        return Permission(str(exc) or "permission denied", op=op)
    if isinstance(exc, ValueError):
        return Validation(str(exc) or "invalid input", op=op)

    message = redact_message(str(exc) or type(exc).__name__)
    name = type(exc).__name__
    upper = message.upper()

    sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "errno", None)
    if sqlstate in {"08001", "08003", "08004", "08006", "08007", "57P01", "57P02", "57P03"}:
        return Transient(message, op=op)
    if sqlstate in {"28000", "390100", "390102", "390114", "390144"}:
        return Auth(message, op=op)
    if sqlstate in {"42501"}:
        return Permission(message, op=op)
    if sqlstate in {"42000", "42601", "22000", "22003", "22007", "22008"}:
        return Validation(message, op=op)

    if name in {"OperationalError", "InterfaceError", "ServiceUnavailableError"}:
        return Transient(message, op=op)
    if name in {"ProgrammingError", "DataError"}:
        return Validation(message, op=op)
    if name in {"DatabaseError"} and any(token in upper for token in ("TIMEOUT", "TIMED OUT")):
        return Timeout(message, op=op)
    if name in {"DatabaseError"} and any(token in upper for token in ("NOT AUTHORIZED", "INSUFFICIENT", "PRIVILEGE")):
        return Permission(message, op=op)
    if name in {"ForbiddenError"}:
        return Permission(message, op=op)

    if any(token in upper for token in ("AUTHENTIC", "LOGIN", "SSO", "TOKEN", "JWT")):
        return Auth(message, op=op)
    if any(token in upper for token in ("TIMEOUT", "TIMED OUT", "STATEMENT_TIMEOUT")):
        return Timeout(message, op=op)
    if any(token in upper for token in ("NOT AUTHORIZED", "INSUFFICIENT", "PRIVILEGE", "READ-ONLY", "NOT ALLOWED")):
        return Permission(message, op=op)
    if any(token in upper for token in ("SYNTAX", "INVALID", "PARSE", "COMPILATION")):
        return Validation(message, op=op)
    if any(token in upper for token in ("NETWORK", "CONNECTION", "UNAVAILABLE", "TEMPORAR")):
        return Transient(message, op=op)

    return Unknown(message, op=op)
