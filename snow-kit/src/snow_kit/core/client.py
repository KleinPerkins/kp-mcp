"""The single API-call choke-point for snow-kit.

Every core function routes its backend call through ``execute`` so cross-cutting
concerns live in exactly one place. The reference kit (google-kit) wraps retry,
error-classification, observability, and audit here using ``kp_mcp_bootstrap``
engines. This template ships the thin version — grow it as the kit matures.
"""
from __future__ import annotations

from typing import Any, Callable

from snow_kit.core.errors import SnowKitError, classify_connector


def execute(api_fn: Callable[[], Any], *, op: str, posture: str) -> Any:
    """Run one backend call.

    Args:
        api_fn:  Zero-arg callable performing the backend request.
        op:      Dotted operation name (e.g. ``query.execute``) — for logs/audit.
        posture: ``read`` | ``write`` | ``destructive`` | ``admin``.

    Returns:
        The raw backend response; the caller wraps it in an ``OutputEnvelope``.
    """
    try:
        return api_fn()
    except SnowKitError:
        raise
    except Exception as exc:  # noqa: BLE001 - backend errors vary by connector version.
        raise classify_connector(exc, op=op) from exc
