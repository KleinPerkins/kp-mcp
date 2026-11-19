"""Service auto-loader for google-kit.

Any package placed under ``google_kit/services/<svc>/`` is automatically
discovered and imported when this module is first imported.  Importing a
service package is sufficient to register its OpSpecs — no shared file
needs editing.

Fan-out workpackets add new services by creating a new directory; they
remain file-disjoint from each other and from this loader.
"""
from __future__ import annotations

import importlib
import pkgutil

_LOADED: bool = False


def load_services() -> None:
    """Import all service packages under ``google_kit.services``.

    Idempotent: subsequent calls are no-ops.
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for _finder, name, _ispkg in pkgutil.iter_modules(__path__):
        importlib.import_module(f"google_kit.services.{name}")


load_services()
