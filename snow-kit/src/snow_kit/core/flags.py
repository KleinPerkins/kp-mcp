"""Runtime gates for snow-kit write posture operations."""
from __future__ import annotations

import os
from typing import Any

from snow_kit.core.errors import SnowKitError

_TRUTHY = {"1", "true", "yes", "on"}
WRITE_FLAG = "SNOW_KIT_ENABLE_WRITE"


class FlagDisabledError(SnowKitError, RuntimeError):
    """Raised when a gated operation is invoked while its flag is disabled."""


def is_flag_enabled(flag: str | None) -> bool:
    """Return true for ungated ops or truthy environment flags."""
    if not flag:
        return True
    return os.environ.get(flag, "").strip().lower() in _TRUTHY


def ensure_enabled(spec: Any) -> None:
    """Reject gated ops unless their explicit opt-in flag is enabled."""
    flag = getattr(spec, "flag", None)
    if is_flag_enabled(flag):
        return
    name = getattr(spec, "name", "?")
    raise FlagDisabledError(
        f"{name} is hidden and disabled until {flag}=1 is set.",
        op=name,
    )
