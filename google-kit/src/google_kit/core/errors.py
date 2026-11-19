"""Error taxonomy for google-kit core (R23).

HTTP→taxonomy mapping is generic; no googleapiclient import — Phase 4 wires
HttpError. CLI exit-code map and structured MCP payload provided per class.
No bare tracebacks to stdout.
"""
from __future__ import annotations

from typing import Any

EXIT_CODES: dict[str, int] = {
    "GoogleKitError": 1,
    "Transient": 2,
    "Auth": 3,
    "QuotaRateLimit": 4,
    "Permission": 5,
    "NotFound": 6,
    "Validation": 7,
    "Conflict": 8,
    "Unknown": 9,
}

_STATUS_MAP: dict[int, str] = {
    400: "Validation",
    401: "Auth",
    403: "Permission",
    404: "NotFound",
    408: "Transient",
    409: "Conflict",
    429: "QuotaRateLimit",
    500: "Transient",
    502: "Transient",
    503: "Transient",
    504: "Transient",
}
# Note: 408 (Request Timeout) is Transient — safe to retry with backoff.
# 410 (Gone) is intentionally absent → falls through to Unknown (not retried):
# the resource is permanently gone, so retrying is futile.


class GoogleKitError(Exception):
    """Base for all google-kit errors.

    Attributes:
        op:      Operation name (e.g. 'drive.fetch').
        context: Additional context dict (redacted before surfacing).
        message: Human-readable redacted description.
    """

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
        self.message = message

    def to_exit_code(self) -> int:
        """Return the CLI exit code for this error class."""
        return EXIT_CODES.get(type(self).__name__, EXIT_CODES["GoogleKitError"])

    def to_mcp_payload(self) -> dict[str, Any]:
        """Return a structured MCP error payload (no traceback)."""
        return {
            "error": type(self).__name__,
            "message": self.message,
            "op": self.op,
        }


class Transient(GoogleKitError):
    """Transient server-side error; safe to retry with backoff."""


class Auth(GoogleKitError):
    """Authentication / token error; do not retry — reauth required."""


class QuotaRateLimit(GoogleKitError):
    """Quota exhausted or rate limit hit; respect Retry-After."""


class Permission(GoogleKitError):
    """Caller lacks permission; do not retry."""


class NotFound(GoogleKitError):
    """Resource not found; do not retry."""


class Validation(GoogleKitError, ValueError):
    """Input failed validation; do not retry.

    Also a :class:`ValueError` so core functions can raise a structured taxonomy
    error for bad input while remaining catchable as a plain ``ValueError`` by
    callers/tests that predate the taxonomy. This is the seam that lets a core
    input guard surface as a structured ``{"error": "Validation", ...}`` MCP
    payload (caught by ``except GoogleKitError``) and a CLI exit code 7, instead
    of leaking an unstructured ``str(exc)`` to the MCP transport.
    """


class Conflict(GoogleKitError):
    """State conflict (e.g. duplicate, version mismatch); do not retry."""


class Unknown(GoogleKitError):
    """Unclassified error; surface to operator."""


_NAME_TO_CLASS: dict[str, type[GoogleKitError]] = {
    "Transient": Transient,
    "Auth": Auth,
    "QuotaRateLimit": QuotaRateLimit,
    "Permission": Permission,
    "NotFound": NotFound,
    "Validation": Validation,
    "Conflict": Conflict,
    "Unknown": Unknown,
}


def classify(
    status_code: int,
    reason: str | None = None,
    *,
    op: str = "",
    context: dict[str, Any] | None = None,
) -> GoogleKitError:
    """Map an HTTP status code (+ optional reason string) to a taxonomy error.

    Phase 4 wires googleapiclient.HttpError → call this with
    e.resp.status and e.error_details.
    """
    message = reason or f"HTTP {status_code}"
    class_name = _STATUS_MAP.get(status_code, "Unknown")
    exc_cls = _NAME_TO_CLASS[class_name]
    return exc_cls(message, op=op, context=context)
