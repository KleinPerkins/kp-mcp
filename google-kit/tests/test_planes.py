"""Plane-model integrity guard (architecture brief §1; E4 review sweep).

Locks in two invariants after the E4 plane normalization + service-default
retrofit:

  1. No op uses a non-canonical plane string (the regression that motivated the
     E1 "structured-content" → "content" normalization).
  2. Every document-seam op carries its canonical §1 plane (via explicit
     declaration or the register() service-default), while Calendar / Tasks /
     Keep — which fall outside the §1 plane taxonomy — remain unplaned.
"""
from __future__ import annotations

import google_kit  # noqa: F401 — triggers registration
from google_kit.registry import all_specs

CANONICAL_PLANES = {
    "container",
    "content",
    "history",
    "eventing",
    "identity",
    "automation",
    "messaging",
}

# Services intentionally outside the §1 document-seam plane taxonomy.
UNPLANED_SERVICES = {"calendar", "tasks", "keep"}

# Default plane each seam service's ops should carry when not eventing/etc.
SEAM_DEFAULT_PLANE = {
    "drive": "container",
    "docs": "content",
    "sheets": "content",
    "slides": "content",
    "forms": "content",
    "gmail": "messaging",
    "people": "identity",
    "script": "automation",
    "drive_activity": "history",
    "events": "eventing",
    "recipes": "content",
}


def _svc(name: str) -> str:
    return name.split(".")[0]


def test_no_op_uses_a_non_canonical_plane() -> None:
    offenders = {
        s.name: s.plane
        for s in all_specs()
        if s.plane is not None and s.plane not in CANONICAL_PLANES
    }
    assert offenders == {}, f"non-canonical planes: {offenders}"


def test_seam_ops_are_planed_and_non_seam_ops_are_not() -> None:
    for s in all_specs():
        svc = _svc(s.name)
        if svc in UNPLANED_SERVICES:
            # Outside the §1 document-seam taxonomy — unplaned, EXCEPT eventing
            # watches (eventing is the cross-API plane: "Workspace Events + per-API
            # watch()"), e.g. calendar.watch.
            assert s.plane in (None, "eventing"), (
                f"{s.name} (outside §1 taxonomy) should be unplaned or eventing, got {s.plane!r}"
            )
        else:
            assert s.plane in CANONICAL_PLANES, f"{s.name} missing a canonical plane (got {s.plane!r})"


def test_seam_default_plane_applied_to_legacy_ops() -> None:
    # Spot-check ops that never declared a plane explicitly (P4 legacy) now carry
    # the §1 service default; and explicit eventing watches still win.
    specs = {s.name: s for s in all_specs()}
    assert specs["drive.create"].plane == "container"
    assert specs["drive.fetch"].plane == "container"
    assert specs["sheets.read"].plane == "content"
    assert specs["slides.create"].plane == "content"
    assert specs["forms.create"].plane == "content"
    assert specs["docs.from_markdown"].plane == "content"
    assert specs["gmail.list"].plane == "messaging"
    # explicit declaration overrides the service default
    assert specs["drive.changes_watch"].plane == "eventing"
    assert specs["gmail.watch"].plane == "eventing"


def test_every_seam_service_default_is_canonical() -> None:
    assert set(SEAM_DEFAULT_PLANE.values()) <= CANONICAL_PLANES
