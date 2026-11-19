"""Declarative capability manifest accessors (architecture brief §1, §2).

The OpSpec registry IS the manifest (single source of truth). This module
reads it as data: it groups ops by capability and plane, parses each op's
ordered adapters, and builds the alias/keyword index that the E6 how-do-I
helper resolves against. No op needs to populate the manifest fields — legacy
1:1 ops simply do not appear in the capability/adapter views.

Planes (§1 plane/seam model):
    container   Drive — identity, discovery, bytes, permissions, change feed
    content     Docs/Sheets/Slides/Forms — per-artifact batchUpdate mutations
    history     Drive Activity v2 — consolidated who/what/when (read-only)
    eventing    Workspace Events + per-API watch() — change subscriptions
    identity    People + Admin SDK Directory — profiles / org graph
    automation  Apps Script — server-side JS escape hatch
    messaging   Gmail — mail read/search/compose/modify
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google_kit.registry import OpSpec, all_specs
from kp_mcp_bootstrap.intent import (
    IntentConfig,
    build_alias_index,
    operation_triggers,
    rank_operations,
    strong_triggers,
    tokenize,
    weak_triggers,
)

PLANES: tuple[str, ...] = (
    "container",
    "content",
    "history",
    "eventing",
    "identity",
    "automation",
    "messaging",
)


@dataclass(frozen=True)
class Adapter:
    """A concrete ``(api, method)`` binding behind a capability (§2).

    Attributes:
        id:          Stable adapter id, e.g. 'drive.export.html'.
        api:         Google API + version, e.g. 'drive.v3'.
        method:      API method, e.g. 'files.export'.
        selector:    Structured predicate (see :mod:`google_kit.core.router`)
                     deciding when this adapter is chosen.
        scopes:      OAuth scopes this adapter requires.
        cost_hint:   Relative cost (api calls / quota units); lower is cheaper.
        fallback_on: Trigger tokens (e.g. '403_export', 'export_unsupported')
                     that make the router advance to the next adapter.
    """

    id: str
    api: str = ""
    method: str = ""
    selector: dict[str, Any] = field(default_factory=dict)
    scopes: tuple[str, ...] = ()
    cost_hint: int | None = None
    fallback_on: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Adapter":
        """Parse an adapter dict (as declared on ``OpSpec.adapters``)."""
        return cls(
            id=str(d["id"]),
            api=str(d.get("api", "")),
            method=str(d.get("method", "")),
            selector=dict(d.get("selector", {})),
            scopes=tuple(d.get("scopes", []) or []),
            cost_hint=d.get("cost_hint"),
            fallback_on=tuple(d.get("fallback_on", []) or []),
        )


def _specs(specs: list[OpSpec] | None) -> list[OpSpec]:
    return list(specs) if specs is not None else all_specs()


def capabilities(specs: list[OpSpec] | None = None) -> dict[str, list[OpSpec]]:
    """Map capability id → ops declaring it (registration order; None skipped)."""
    out: dict[str, list[OpSpec]] = {}
    for s in _specs(specs):
        cap = getattr(s, "capability", None)
        if cap:
            out.setdefault(cap, []).append(s)
    return out


def adapters_for(capability: str, specs: list[OpSpec] | None = None) -> list[Adapter]:
    """Return the ordered adapters declared for a capability (across its ops)."""
    out: list[Adapter] = []
    for s in capabilities(specs).get(capability, []):
        for d in getattr(s, "adapters", []) or []:
            out.append(Adapter.from_dict(d))
    return out


def ops_by_plane(specs: list[OpSpec] | None = None) -> dict[str, list[str]]:
    """Map plane → sorted op names assigned to it."""
    out: dict[str, list[str]] = {}
    for s in _specs(specs):
        plane = getattr(s, "plane", None)
        if plane:
            out.setdefault(plane, []).append(s.name)
    return {k: sorted(v) for k, v in out.items()}


def alias_index(specs: list[OpSpec] | None = None) -> dict[str, str]:
    """Build a lowercase trigger → op-name index for the E6 helper.

    Includes each op's dotted name, its CLI form (``svc op``), and every
    declared alias/keyword. Later declarations do not override earlier ones
    (first registration wins) so the mapping is deterministic.
    """
    return build_alias_index(_specs(specs))


# ── E6: intent resolver (the "how do I …?" helper) ────────────────────────────
#
# Every op is discoverable WITHOUT per-op boilerplate via two single-engine
# layers, augmented by any explicit OpSpec.aliases/keywords:
#   1. _SERVICE_TRIGGERS — synonym keywords shared by every op in a service.
#   2. name tokens         — the op's own dotted-name words (split on . and _).
# A small _CURATED_ALIASES map adds natural-language phrases for the workhorse
# ops where the human phrasing diverges from the op name; these are the curated
# triggers an operator reviews/signs off at gate (b). New explicit phrases can
# be promoted onto OpSpec.aliases at any time (the recipes already are).

_SERVICE_TRIGGERS: dict[str, tuple[str, ...]] = {
    "drive": ("file", "files", "folder", "folders", "document", "upload", "download", "share", "permission", "storage"),
    "docs": ("doc", "document", "word", "writeup"),
    "sheets": ("spreadsheet", "sheet", "excel", "cell", "cells", "row", "column", "table"),
    "slides": ("slide", "slides", "presentation", "deck", "powerpoint"),
    "forms": ("form", "forms", "survey", "quiz", "questionnaire", "poll"),
    "gmail": ("email", "mail", "message", "messages", "inbox", "reply", "thread"),
    "calendar": ("event", "events", "meeting", "schedule", "appointment", "invite", "availability"),
    "tasks": ("task", "tasks", "todo", "to-do", "reminder", "checklist"),
    "keep": ("note", "notes", "memo", "checklist"),
    "people": ("contact", "contacts", "person", "people", "directory", "profile", "coworker", "colleague"),
    "script": ("script", "automation", "macro", "function", "apps-script"),
    "events": ("subscription", "webhook", "notification", "watch", "push", "subscribe"),
    "drive_activity": ("activity", "history", "audit", "changes", "who", "when"),
    "recipes": ("workflow", "recipe", "compose", "pipeline", "multi-step"),
}

_CURATED_ALIASES: dict[str, tuple[str, ...]] = {
    "gmail.send": ("send an email", "compose and send mail", "email someone"),
    "gmail.draft": ("draft an email", "save a draft"),
    "gmail.list": ("check my inbox", "list emails", "recent mail"),
    "gmail.search": ("find an email", "search mail"),
    "gmail.modify": ("label an email", "mark as read", "archive a message"),
    "drive.search": ("find a file", "search drive", "locate a document"),
    "drive.fetch": ("download a file", "get file contents", "read a document", "open a doc"),
    "drive.create": ("make a new file", "create a document in drive"),
    "drive.permissions": ("share a file", "grant access", "add a collaborator"),
    "drive.copy": ("duplicate a file", "make a copy"),
    "drive.trash": ("delete a file", "move to trash"),
    "calendar.create": ("schedule a meeting", "create an event", "book time"),
    "calendar.list": ("what's on my calendar", "list events", "my schedule"),
    "calendar.freebusy": ("check availability", "when am i free", "find free time"),
    "sheets.create": ("make a spreadsheet", "new sheet"),
    "sheets.read": ("read spreadsheet data", "get cell values"),
    "sheets.write": ("update cells", "write to a sheet"),
    "docs.from_markdown": ("create a doc from markdown", "publish markdown as a google doc"),
    "tasks.create": ("add a todo", "create a task", "remind me to"),
    "slides.create": ("make a presentation", "new slide deck"),
    "forms.create": ("create a form", "make a survey"),
    "forms.add_item": ("add a question", "add a question to a form", "add an item to a survey"),
    "people.search_directory": ("find a coworker", "search the directory"),
    "people.get": ("look up a contact", "get someone's profile"),
    "drive_activity.query": ("who changed a file", "file change history"),
}

_STOPWORDS = frozenset(
    "a an the how do i to my in of for with on and or is it me can please "
    "this that from into".split()
)


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens (len ≥ 2), stopwords removed — deterministic."""
    return tokenize(text, stopwords=_STOPWORDS)


def curated_aliases(op: str) -> tuple[str, ...]:
    """Curated natural-language intent phrases for *op* (empty if none)."""
    return _CURATED_ALIASES.get(op, ())


def _extra_strong_terms(spec: OpSpec) -> tuple[str, ...]:
    capability = getattr(spec, "capability", None)
    return (str(capability),) if capability else ()


_INTENT_CONFIG = IntentConfig(
    service_triggers=_SERVICE_TRIGGERS,
    curated_aliases=_CURATED_ALIASES,
    stopwords=_STOPWORDS,
    extra_strong_terms=_extra_strong_terms,
)


def _strong_triggers(spec: OpSpec) -> set[str]:
    """Discriminating tokens: name words, capability words, curated/explicit phrases."""
    return strong_triggers(spec, _INTENT_CONFIG)


def _weak_triggers(spec: OpSpec) -> set[str]:
    """Service-synonym tokens, shared by every op in a service (weakly weighted)."""
    return weak_triggers(spec, _INTENT_CONFIG)


def op_triggers(spec: OpSpec) -> set[str]:
    """Full lowercase trigger token set for *spec* (strong ∪ weak) — for the manifest/report."""
    return operation_triggers(spec, _INTENT_CONFIG)


@dataclass(frozen=True)
class IntentMatch:
    """A ranked intent-resolution hit: which op, how strongly, and why."""

    op: str
    score: float
    matched: tuple[str, ...]


def resolve_intent(
    query: str, specs: list[OpSpec] | None = None, *, limit: int = 5
) -> list[IntentMatch]:
    """Resolve a natural-language *query* to ranked ops (the E6 help engine).

    Scoring (deterministic; ties broken by op name):
      +10   exact phrase match of the whole query (op name, CLI form, or a
            curated/explicit alias phrase)
      +1.0  per distinct query token in the op's STRONG triggers (name /
            capability / curated-alias words — discriminating)
      +0.5  per distinct query token in the op's WEAK triggers (service
            synonyms — shared within a service, discriminating only across them)
      +1.5  the op's terminal verb (last name segment) is a query token
    """
    return [
        IntentMatch(match.operation, match.score, match.matched_cues)
        for match in rank_operations(
            query,
            _specs(specs),
            _INTENT_CONFIG,
            limit=limit,
        )
    ]
