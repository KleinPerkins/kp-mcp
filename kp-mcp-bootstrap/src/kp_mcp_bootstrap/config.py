"""Config resolution for kp-mcp-bootstrap consumers.

Resolves the active config directory, profile, and headless flag from the
environment with the following precedence rules:

Config dir:
  1. GOOGLE_KIT_CONFIG_DIR env var (absolute path)
  2. $CHAOS_LABS_ROOT/data/google-kit/ (if CHAOS_LABS_ROOT is set)
  3. ~/Library/Application Support/google-kit/ (default)

Profile:
  GOOGLE_KIT_PROFILE env var (default: "default")

Headless:
  GOOGLE_KIT_HEADLESS or CHAOS_LABS_HEADLESS — truthy: "1", "true", "yes" (case-insensitive)
"""

import os
from pathlib import Path

from pydantic import BaseModel

from kp_mcp_bootstrap.errors import ConfigError

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in _TRUTHY


def _resolve_config_dir() -> Path:
    explicit = os.environ.get("GOOGLE_KIT_CONFIG_DIR")
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            raise ConfigError(
                f"GOOGLE_KIT_CONFIG_DIR must be an absolute path, got: {explicit!r}"
            )
        return p

    chaos_root = os.environ.get("CHAOS_LABS_ROOT")
    if chaos_root:
        return Path(chaos_root) / "data" / "google-kit"

    return Path.home() / "Library" / "Application Support" / "google-kit"


class Config(BaseModel):
    """Resolved runtime configuration for a kp-mcp-bootstrap consumer."""

    config_dir: Path
    profile: str
    headless: bool

    model_config = {"frozen": True}


def load_config() -> Config:
    """Resolve Config from the environment.

    Raises ConfigError if any resolved value is invalid.
    """
    config_dir = _resolve_config_dir()
    profile = os.environ.get("GOOGLE_KIT_PROFILE", "default").strip()
    if not profile:
        raise ConfigError("GOOGLE_KIT_PROFILE must not be empty.")

    headless_raw = os.environ.get("GOOGLE_KIT_HEADLESS") or os.environ.get("CHAOS_LABS_HEADLESS", "")
    headless = _parse_bool(headless_raw)

    return Config(config_dir=config_dir, profile=profile, headless=headless)
