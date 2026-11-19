"""Single source of truth for all google-kit capabilities.

Each capability is registered once as an OpSpec. CLI, MCP, and docgen all
derive from this registry — adding a capability means one core function + one
registry entry, then both surfaces and docs update automatically.

OpSpec fields mirror the contract in kp_mcp_bootstrap.docgen.OpSpecLike.
"""

import re
from typing import Any, Callable

from pydantic import BaseModel

from kp_mcp_bootstrap.docgen import OpSpecLike


_VALID_POSTURES = {"read", "write", "admin", "destructive"}
_OPSPEC_NAME_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")


class OpSpec:
    """Registry entry for one google-kit capability.

    The registry is the single source of truth (the architecture-brief §2
    "declarative manifest"): CLI, MCP schemas, and docgen all derive from it.
    The base fields below define the 1:1 capability contract. The manifest
    fields (``capability``..``recipe``) are OPTIONAL and additive — they let a
    capability declare its plane (§1), its ordered adapters with selectors /
    cost-hints / fallback triggers (§2 router), its trigger aliases/keywords
    (E6 helper), and its composition recipe (§4 saga). Legacy 1:1 ops leave
    them empty and are unaffected.

    Attributes:
        name:         Unique dotted name, e.g. 'drive.fetch'.
        fn:           Core function (typed in/out models; no argparse; logs to stderr).
        input_model:  Pydantic model class for the operation's input.
        output_model: Pydantic model class for the operation's output envelope.
        posture:      One of 'read', 'write', 'admin', 'destructive'.
        scopes:       OAuth scopes required.
        perf:         Performance/quota metadata dict.
        batching:     Batching configuration dict.
        formatting:   Output formatting hints dict.
        examples:     List of runnable example dicts (schema, scopes, perf…).
        capability:   Artifact-neutral capability id this op serves, e.g. 'doc.read'
                      (§2). None for a plain 1:1 op.
        plane:        Plane/seam this op belongs to (§1): 'container' | 'content' |
                      'history' | 'eventing' | 'identity' | 'automation' | 'messaging'.
        adapters:     Ordered list of adapter dicts the router may select among
                      (id, api, method, selector, scopes, cost_hint, fallback_on).
        aliases:      Trigger phrases/aliases that resolve to this op (E6 manifest).
        keywords:     Intent keywords for the how-do-I helper (E6).
        recipe:       Composition-recipe id (§4) if this op realizes a multi-API
                      recipe with LIFO saga compensation.
        flag:         Env-var name gating CLI/MCP execution (ADR F5 off-by-default).
                      None = always enabled. Set e.g. 'GOOGLE_KIT_ENABLE_GMAIL_WRITE'
                      to require an explicit operator opt-in before the op runs.
    """

    def __init__(
        self,
        name: str,
        fn: Callable[..., Any],
        input_model: type[BaseModel],
        output_model: type[BaseModel],
        posture: str,
        scopes: list[str],
        perf: dict[str, Any] | None = None,
        batching: dict[str, Any] | None = None,
        formatting: dict[str, Any] | None = None,
        examples: list[Any] | None = None,
        capability: str | None = None,
        plane: str | None = None,
        adapters: list[dict[str, Any]] | None = None,
        aliases: list[str] | None = None,
        keywords: list[str] | None = None,
        recipe: str | None = None,
        flag: str | None = None,
    ) -> None:
        if not isinstance(name, str) or not _OPSPEC_NAME_RE.fullmatch(name):
            raise ValueError(
                "OpSpec name must be a non-empty dotted identifier "
                "containing only letters, numbers, and underscores."
            )
        if not callable(fn):
            raise TypeError("OpSpec fn must be callable.")
        if not isinstance(input_model, type) or not issubclass(input_model, BaseModel):
            raise TypeError("OpSpec input_model must be a pydantic BaseModel class.")
        if not isinstance(output_model, type) or not issubclass(output_model, BaseModel):
            raise TypeError("OpSpec output_model must be a pydantic BaseModel class.")
        if posture not in _VALID_POSTURES:
            raise ValueError(
                f"OpSpec posture must be one of {sorted(_VALID_POSTURES)!r}; got {posture!r}."
            )
        self.name = name
        self.fn = fn
        self.input_model = input_model
        self.output_model = output_model
        self.posture = posture
        self.scopes = scopes
        self.perf = perf or {}
        self.batching = batching or {}
        self.formatting = formatting or {}
        self.examples = examples or []
        self.capability = capability
        self.plane = plane
        self.adapters = adapters or []
        self.aliases = tuple(aliases or ())
        self.keywords = tuple(keywords or ())
        self.recipe = recipe
        self.flag = flag

    def satisfies_opspec_like(self) -> bool:
        """Verify this instance satisfies the OpSpecLike protocol."""
        return isinstance(self, OpSpecLike)


_REGISTRY: dict[str, OpSpec] = {}

# §1 plane defaults for the document-seam services (architecture brief §1 table).
# Applied only when an OpSpec does not declare ``plane`` explicitly — explicit
# per-op declarations always win (e.g. a `*.watch` op sets plane="eventing").
# Calendar / Tasks / Keep are intentionally ABSENT: they fall outside the §1
# document-seam plane taxonomy and remain unplaned until the taxonomy is
# extended (an operator decision, not an autonomous one).
_SEAM_PLANE_BY_SERVICE: dict[str, str] = {
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


def register(spec: OpSpec) -> OpSpec:
    """Add an OpSpec to the registry. Raises if name is already registered.

    Fills in a §1 service-default ``plane`` when the op did not declare one, so
    every document-seam op carries a canonical plane without per-op boilerplate.
    """
    if not spec.scopes or any(not isinstance(scope, str) or not scope.strip() for scope in spec.scopes):
        raise ValueError("OpSpec scopes must contain at least one non-empty scope string.")
    if spec.name in _REGISTRY:
        raise ValueError(f"OpSpec {spec.name!r} is already registered.")
    if spec.plane is None:
        spec.plane = _SEAM_PLANE_BY_SERVICE.get(spec.name.split(".")[0])
    _REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> OpSpec:
    """Retrieve a registered OpSpec by name. Raises KeyError if absent."""
    return _REGISTRY[name]


def all_specs() -> list[OpSpec]:
    """Return all registered OpSpec entries in registration order."""
    return list(_REGISTRY.values())
