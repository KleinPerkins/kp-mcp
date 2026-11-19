"""Real-auth service builder: maps service prefix to Google API (api_name, version).

CLI and MCP adapters call build_service_for_op to obtain an authorized
googleapiclient Resource backed by the macOS Keychain.

Tests inject a service directly via the core-fn ``service=`` parameter and
never call this module.
"""
from __future__ import annotations

from typing import Any

# Full OAuth scope set for the single-consent flow (legacy parity).
# keep is excluded: it is a Workspace-only API that requires a separate,
# often-failing consumer consent flow not required for cutover-minimum.
#
# This is the single, shared consent UNION for the whole kit. It intentionally
# keeps the read-WRITE scopes (spreadsheets/presentations/calendar/tasks/
# forms.body) because the same services' write ops require them, and a
# read-write scope functionally subsumes its .readonly variant. The gate-(c)
# least-privilege tightening (2026-06-17) narrowed per-op OpSpec.scopes for the
# pure-read ops to their .readonly variants (router/observability/docs/manifest
# truth) but does NOT change this grant: reads keep working under the held rw
# token, so NO re-consent is required. Shrinking this union to .readonly would
# strip write capability from those services (cutover-parity regression) and is
# only viable via a separate read-only consent profile (future, operator-gated).
GOOGLE_KIT_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
]

_SERVICE_API_MAP: dict[str, tuple[str, str]] = {
    "calendar": ("calendar", "v3"),
    "docs": ("docs", "v1"),
    "drive": ("drive", "v3"),
    "drive_activity": ("driveactivity", "v2"),
    "events": ("workspaceevents", "v1"),
    "forms": ("forms", "v1"),
    "gmail": ("gmail", "v1"),
    "keep": ("keep", "v1"),
    "people": ("people", "v1"),
    "script": ("script", "v1"),
    "sheets": ("sheets", "v4"),
    "slides": ("slides", "v1"),
    "tasks": ("tasks", "v1"),
}


def build_service_for_op(op_name: str, *, profile: str | None = None) -> Any:
    """Build an authorized Google API service for the given op name.

    Args:
        op_name: Dotted op name, e.g. ``'tasks.list_lists'``. The prefix before
                 the first dot determines the Google API.
        profile: Keychain profile override. When omitted, the sandbox guardrail
                 (``GOOGLE_KIT_SANDBOX=1`` → sandbox profile) applies; otherwise
                 defaults to GOOGLE_KIT_PROFILE env var or ``'default'``.

    Returns:
        Authorized ``googleapiclient`` Resource.

    Raises:
        KeyError: If the service prefix is not in ``_SERVICE_API_MAP``.
        RuntimeError: If not on macOS (Keychain unavailable).
        kp_mcp_bootstrap.errors.SecretStoreError: If required tokens are absent
            from the macOS Keychain.
    """
    from kp_mcp_bootstrap.config import load_config
    from kp_mcp_bootstrap.secrets import KeychainSecretStore

    from google_kit.core.audit import set_actor
    from google_kit.core.client import build_authorized_service
    from google_kit.core.sandbox import resolve_profile

    from .personal_runtime import current
    runtime = current()
    if runtime is not None:
        return runtime.service(op_name, profile)

    cfg = load_config()
    active_profile = resolve_profile(profile) or cfg.profile
    # Attribute audited mutations to the resolved profile (the single place the
    # active profile is known). Service core fns call execute_api_call without an
    # actor, so without this the audit ``actor`` is always the hardcoded default.
    set_actor(active_profile)
    prefix = op_name.split(".")[0]
    if prefix not in _SERVICE_API_MAP:
        raise KeyError(f"No API mapping for service prefix {prefix!r}")
    api_name, api_version = _SERVICE_API_MAP[prefix]

    store = KeychainSecretStore(profile=active_profile)
    client_id = store.get("client_id")
    return build_authorized_service(api_name, api_version, store, client_id=client_id)
