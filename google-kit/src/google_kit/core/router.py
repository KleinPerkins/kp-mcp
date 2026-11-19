"""Deterministic capability router (architecture brief §2).

Resolves ``(capability, context) → Plan`` where the plan is one adapter, an
ordered fallback chain (Chain-of-Responsibility), or a composition recipe.
The router is PURE: it selects; it does not call Google. Adapter execution +
LIFO saga compensation live in the service/recipe layer (E1/E3). This keeps
routing transparent and unit-testable, and is the seam through which the kit
is "thick on reads/composition" while writes stay thin/explicit.

Selector predicate language (declared on each adapter's ``selector`` dict):
    {}                         → always matches (default / catch-all)
    {"any": True}              → always matches
    {"k": v, ...}              → AND: every key must equal context[k]
    {"any_of": [pred, ...]}    → OR: at least one sub-predicate matches
    base keys AND any_of may be combined on one selector.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google_kit.core.manifest import Adapter, adapters_for


@dataclass(frozen=True)
class Plan:
    """A resolved execution plan for a capability.

    Attributes:
        capability:    Capability id resolved.
        kind:          'single' | 'fallback' | 'recipe' | 'none'.
        chosen:        The primary adapter (None if nothing eligible).
        fallback_chain: Remaining eligible adapters, in cascade order.
        recipe_id:     Recipe id if this capability is a composition recipe.
        reason:        Human-readable resolution explanation (for the envelope).
    """

    capability: str
    kind: str
    chosen: Adapter | None = None
    fallback_chain: tuple[Adapter, ...] = ()
    recipe_id: str | None = None
    reason: str = ""

    @property
    def fallback_used(self) -> bool:
        """True once a caller advances past ``chosen`` into the chain."""
        return False


def selector_matches(selector: dict[str, Any], context: dict[str, Any]) -> bool:
    """Evaluate a structured selector predicate against a context (deterministic)."""
    if not selector or selector.get("any") is True:
        return True
    for key, expected in selector.items():
        if key == "any":
            continue
        if key == "any_of":
            if not any(selector_matches(sub, context) for sub in expected):
                return False
            continue
        if context.get(key) != expected:
            return False
    return True


def _scope_eligible(adapter: Adapter, granted_scopes: set[str] | None) -> bool:
    """An adapter is eligible only if its required scopes are all granted.

    If ``granted_scopes`` is None the caller has not declared a scope set, so
    scope-gating is skipped (all adapters remain eligible).
    """
    if granted_scopes is None:
        return True
    return set(adapter.scopes).issubset(granted_scopes)


def resolve(
    capability: str,
    context: dict[str, Any] | None = None,
    *,
    granted_scopes: list[str] | set[str] | None = None,
    recipe_id: str | None = None,
    specs: Any = None,
) -> Plan:
    """Resolve a capability to a :class:`Plan`.

    Args:
        capability:     Capability id, e.g. 'doc.read'.
        context:        Routing context (intent, will_edit, needs_indices, …).
        granted_scopes: OAuth scopes the caller holds; gates adapters by scope.
                        None → no scope-gating.
        recipe_id:      If set, mark the plan as a composition recipe (§4).
        specs:          Optional explicit OpSpec list (for tests / isolation).

    Returns:
        A deterministic Plan. ``kind='none'`` with no chosen adapter when no
        eligible adapter's selector matches.
    """
    ctx = dict(context or {})
    granted = set(granted_scopes) if granted_scopes is not None else None

    eligible = [a for a in adapters_for(capability, specs) if _scope_eligible(a, granted)]
    matched = [a for a in eligible if selector_matches(a.selector, ctx)]

    if recipe_id is not None:
        return Plan(
            capability=capability,
            kind="recipe",
            chosen=matched[0] if matched else None,
            fallback_chain=tuple(matched[1:]),
            recipe_id=recipe_id,
            reason=f"recipe:{recipe_id}",
        )

    if not matched:
        return Plan(
            capability=capability,
            kind="none",
            reason="no eligible adapter matched the context"
            + ("" if granted is None else " under granted scopes"),
        )

    chosen, *rest = matched
    kind = "fallback" if rest else "single"
    return Plan(
        capability=capability,
        kind=kind,
        chosen=chosen,
        fallback_chain=tuple(rest),
        reason=f"selected {chosen.id}"
        + (f"; {len(rest)} fallback(s)" if rest else ""),
    )
