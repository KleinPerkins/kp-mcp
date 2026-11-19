"""Service auto-loader for snow-kit.

Any package placed under ``snow_kit/services/<svc>/`` is discovered and imported
on first import of this module — importing a service package registers its
OpSpecs. Add a new service by creating a new directory; no shared file edits.
"""
from __future__ import annotations

import importlib
import pkgutil

_LOADED: bool = False


def load_services() -> None:
    """Import all service packages under ``snow_kit.services`` (idempotent)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for _finder, name, _ispkg in pkgutil.iter_modules(__path__):
        importlib.import_module(f"snow_kit.services.{name}")


load_services()
