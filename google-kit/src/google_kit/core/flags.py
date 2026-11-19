"""Per-profile write authorization + ADR-F5 environment overrides.

Every ``write`` / ``destructive`` op is registered and documented like any other
capability, but is refused at the CLI / MCP execution boundary unless it is
*authorized for the active profile*. An op declares that it requires
authorization by carrying ``OpSpec.flag = "<ENV_VAR_NAME>"`` (every mutating op
does; read/admin ops carry none). The gate is an adapter-layer concern, not part
of the core logic, so the core functions stay pure and directly unit-testable.

Authorization model — a gated op passes when EITHER holds:

* **Per-profile grant (primary)** — the active profile has granted the op
  (config value ``1``; default ``0``/deny). Managed per profile with
  ``google-kit auth grant <op> --profile <p>`` / ``revoke`` and stored under the
  config dir. See :mod:`google_kit.core.authz`.
* **Environment override (escape hatch)** — the op's own
  ``GOOGLE_KIT_ENABLE_<SERVICE>_WRITE`` env var is truthy, or — for per-service
  ``*_WRITE`` gates only — the ``GOOGLE_KIT_ENABLE_WRITES`` umbrella is truthy.
  The umbrella deliberately does **not** satisfy elevated gates whose names do
  not end in ``_WRITE`` (``GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE`` world-readable
  exposure, ``GOOGLE_KIT_ENABLE_DRIVE_WATCH`` push-channel eventing).

NOTE: value-conditional in-core guards that call :func:`is_flag_enabled` directly
(e.g. Drive world-readable "public share") are an independent data-exposure
safeguard and remain in force regardless of any per-profile grant.
"""
from __future__ import annotations

import os
from typing import Any

from google_kit.core.errors import GoogleKitError

_TRUTHY = {"1", "true", "yes", "on"}

#: Umbrella opt-in: when truthy, satisfies every per-service ``*_WRITE`` gate.
ENABLE_WRITES_FLAG = "GOOGLE_KIT_ENABLE_WRITES"


class FlagDisabledError(GoogleKitError, RuntimeError):
    """Raised when a gated op is invoked without authorization (no per-profile
    grant and no enabling env override)."""


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def is_flag_enabled(flag: str | None) -> bool:
    """Return True if *flag* is falsy/None (ungated) or enabled.

    A flag is enabled when its own env var is truthy, OR — for per-service write
    gates (names ending in ``_WRITE``) — when the umbrella ``GOOGLE_KIT_ENABLE_WRITES``
    is truthy. Elevated gates not ending in ``_WRITE`` (e.g. public-share, watch)
    are never satisfied by the umbrella.
    """
    from .personal_runtime import current
    runtime = current()
    if runtime is not None:
        return runtime.flag(flag)
    if not flag:
        return True
    if _env_truthy(flag):
        return True
    if flag.endswith("_WRITE") and _env_truthy(ENABLE_WRITES_FLAG):
        return True
    return False


def ensure_enabled(spec: Any, *, profile: str | None = None) -> None:
    """Refuse a gated op unless it is authorized for the active profile.

    A tool that requires authorization (``OpSpec.flag`` set — every ``write`` /
    ``destructive`` op) passes when EITHER the active profile has granted it
    (per-profile config value ``1``) OR a runtime env override is set (its own
    ``flag``, or the ``GOOGLE_KIT_ENABLE_WRITES`` umbrella for ``*_WRITE`` gates).
    Otherwise it raises :class:`FlagDisabledError`. Ops that require no
    authorization (no ``flag``) always pass.

    Args:
        spec: The op spec being invoked.
        profile: Explicit profile (the CLI ``--profile`` value). When ``None`` the
            active profile is resolved the same way the service builder resolves it
            (sandbox guardrail, then ``GOOGLE_KIT_PROFILE`` / ``"default"``), so the
            grant consulted matches the identity the call runs as.
    """
    from .personal_runtime import current
    runtime = current()
    if runtime is not None:
        runtime.authorize(spec, profile)
        return
    from google_kit.core.authz import (
        is_authorized,
        requires_authorization,
        resolve_active_profile,
    )

    if not requires_authorization(spec):
        return

    flag = getattr(spec, "flag", None)
    if flag and is_flag_enabled(flag):
        return  # runtime env override (escape hatch)

    active = resolve_active_profile(profile)
    name = getattr(spec, "name", "?")
    if is_authorized(active, name):
        return

    hint = f"Authorize it for this profile with: google-kit auth grant {name} --profile {active}"
    if flag:
        if flag.endswith("_WRITE"):
            hint += (
                f" (or set {flag}=1, or {ENABLE_WRITES_FLAG}=1 for all service write ops)"
            )
        else:
            hint += f" (or set {flag}=1)"
    raise FlagDisabledError(
        f"{name} is not authorized for profile {active!r}. {hint}",
        op=name,
    )
