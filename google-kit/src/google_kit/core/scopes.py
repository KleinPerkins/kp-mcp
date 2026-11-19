"""Least-privilege per-mode OAuth scope manifest (architecture brief §8).

Encodes the brief's "least-privilege scope manifest (by mode)" so bootstrap
can request only the scopes a chosen mode needs, and so capabilities can
declare which mode they run under. This is the manifest of record; the
*currently consented* live set is :data:`google_kit.core.auth.GOOGLE_KIT_SCOPES`
(the proven cutover-minimum set). New modes here (Gmail-write, advanced,
activity/directory) require operator scope approval + sandbox consent before
they are added to the live consent flow — they are declared, not yet granted.
"""
from __future__ import annotations

_BASE = "https://www.googleapis.com/auth/"


def _s(*names: str) -> tuple[str, ...]:
    return tuple(_BASE + n for n in names)


# Mode → required scopes (brief §8). Modes compose: a session requests the
# union of the modes it enables. read_ingest is the default least-privilege mode.
SCOPE_MODES: dict[str, tuple[str, ...]] = {
    # Read / ingest (default).
    "read_ingest": _s(
        "drive.readonly",
        "documents.readonly",
        "spreadsheets.readonly",
        "presentations.readonly",
        "forms.body.readonly",
        "forms.responses.readonly",
        "drive.activity.readonly",
        "gmail.readonly",
        "directory.readonly",
        "contacts.readonly",
        # people.get reads people/me (the user's own PROFILE source), which
        # directory/contacts scopes do not authorize — names/emailAddresses for
        # people/me require the profile scope (live 403 "[profile]"). Declared
        # here for manifest parity with the people.get OpSpec; requested as an
        # EXTRA per-login consent (GOOGLE_KIT_EXTRA_SCOPES), NOT added to the
        # shared grant core/auth.py:GOOGLE_KIT_SCOPES. See LIVE-E2E-NEW-APIS.md §1.
        "userinfo.profile",
        # Calendar/Tasks read ops tightened to .readonly at gate (c) — keep the
        # default read mode consistent with their per-op least-privilege scopes.
        "calendar.readonly",
        "tasks.readonly",
    ),
    # Create / edit (per-file).
    "create_edit": _s(
        "drive.file",
        "documents",
        "spreadsheets",
        "presentations",
        "forms.body",
    ),
    # Broad authoring / share — escalate drive.file → drive.
    "broad_authoring": _s("drive"),
    # Gmail write (off-by-default flag; F5).
    "gmail_write": _s("gmail.compose", "gmail.modify"),
    # Workspace Events subscriptions (Drive targets per §7). subscriptions.{create,
    # list,patch,delete} authorize using the TARGET resource's scope — there is no
    # dedicated Workspace Events scope. The kit's events.* ops target Drive, so the
    # authorizing scope is drive.readonly (already in read_ingest + the live consent
    # union). Cloud Pub/Sub topic provisioned separately by the operator.
    "events": _s("drive.readonly"),
    # Advanced (admin / automation) — admin consent gated (F6).
    "advanced": _s(
        "admin.directory.readonly",
        # Keep is Workspace-only and domain-admin enabled. It is intentionally
        # outside the live shared grant, but its ops still need a satisfiable
        # explicit consent mode for allowlisted Workspace tenants.
        "keep",
        "keep.readonly",
        "script.projects",
        "script.deployments",
        "script.external_request",
        # projects.getMetrics authorizes ONLY via the dedicated script.metrics
        # scope (script.projects[.readonly] do not cover it). Declared here for
        # manifest parity with the script.metrics OpSpec; requested per-login as
        # an EXTRA consent (GOOGLE_KIT_EXTRA_SCOPES), NOT added to the shared
        # grant core/auth.py:GOOGLE_KIT_SCOPES. See LIVE-E2E-NEW-APIS.md §1.
        "script.metrics",
    ),
}

DEFAULT_MODE = "read_ingest"


def all_modes() -> list[str]:
    """Return the declared mode names in manifest order."""
    return list(SCOPE_MODES)


def scopes_for_modes(modes: list[str] | tuple[str, ...]) -> list[str]:
    """Return the deduplicated, deterministically-ordered scope union for modes.

    Raises:
        KeyError: If any mode is unknown.
    """
    seen: dict[str, None] = {}
    for mode in modes:
        if mode not in SCOPE_MODES:
            raise KeyError(f"Unknown scope mode {mode!r}; known: {', '.join(SCOPE_MODES)}")
        for scope in SCOPE_MODES[mode]:
            seen.setdefault(scope, None)
    return sorted(seen)
