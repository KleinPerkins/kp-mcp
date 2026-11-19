"""Single source of truth for all snow-kit capabilities.

Register each capability once as an ``OpSpec``; the CLI, MCP server, ``schema_gen``
and ``docgen_gen`` all derive from this registry — adding a capability is one core
function plus one ``register(...)`` call, and both surfaces plus the docs update.

``OpSpec`` satisfies the ``kp_mcp_bootstrap.docgen.OpSpecLike`` protocol so the
shared docgen engine works without a circular dependency.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from pydantic import BaseModel

from kp_mcp_bootstrap.docgen import OpSpecLike

_VALID_POSTURES = {"read", "write", "destructive", "admin"}
_OPSPEC_NAME_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")
_DEFAULT_ERRORS = [
    {
        "class": "Auth",
        "when": "Snowflake SSO or cached authentication is unavailable",
        "retry": "Run snow-kit auth login; do not retry unchanged",
    },
    {
        "class": "Permission",
        "when": "Live grants or a server-side safety policy denies the request",
        "retry": "Do not retry unchanged",
    },
    {
        "class": "Validation",
        "when": "Arguments, SQL, context references, or configuration are invalid",
        "retry": "Correct the input, then retry once",
    },
    {
        "class": "Unavailable",
        "when": "An approved local context source cannot be read safely",
        "retry": "Repair setup or source state; never treat as no matches",
    },
    {
        "class": "Timeout",
        "when": "A tool, query, or local lock exceeds its configured limit",
        "retry": "Narrow the request; no automatic retry",
    },
    {
        "class": "Transient",
        "when": "The Snowflake connection fails transiently",
        "retry": "Retry once only when the operation is idempotent",
    },
    {
        "class": "Unknown",
        "when": "The failure cannot be classified safely",
        "retry": "Escalate; do not retry automatically",
    },
]


class OpSpec:
    """Registry entry for one snow-kit capability.

    Attributes:
        name:         Unique dotted name, e.g. ``query.execute``.
        fn:           Typed core function (Pydantic in / Pydantic out; no argparse).
        input_model:  Pydantic model class for the operation's input.
        output_model: Pydantic ``OutputEnvelope[...]`` model class.
        posture:      One of ``read`` | ``write`` | ``destructive`` | ``admin``.
        scopes:       Auth scopes required.
        perf:         Performance / quota metadata.
        batching:     Batching configuration.
        formatting:   Output formatting hints.
        examples:     Runnable example dicts (description / input / cli).
        aliases:      Natural-language trigger phrases (intent helper).
        keywords:     Intent keywords (intent helper).
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
        aliases: list[str] | None = None,
        keywords: list[str] | None = None,
        flag: str | None = None,
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        if not isinstance(name, str) or not _OPSPEC_NAME_RE.fullmatch(name):
            raise ValueError("OpSpec name must be a dotted identifier.")
        if posture not in _VALID_POSTURES:
            raise ValueError(f"OpSpec posture must be one of {sorted(_VALID_POSTURES)!r}.")
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
        self.aliases = aliases or []
        self.keywords = keywords or []
        self.flag = flag
        self.errors = [
            dict(item)
            for item in (_DEFAULT_ERRORS if errors is None else errors)
        ]

    def satisfies_opspec_like(self) -> bool:
        """Verify this instance satisfies the OpSpecLike protocol."""
        return isinstance(self, OpSpecLike)


_REGISTRY: dict[str, OpSpec] = {}


def register(spec: OpSpec) -> OpSpec:
    """Add an OpSpec to the registry. Raises if the name is already registered."""
    if spec.name in _REGISTRY:
        raise ValueError(f"OpSpec {spec.name!r} is already registered.")
    _REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> OpSpec:
    """Retrieve a registered OpSpec by name. Raises KeyError if absent."""
    return _REGISTRY[name]


def all_specs() -> list[OpSpec]:
    """Return all registered OpSpec entries in registration order."""
    return list(_REGISTRY.values())
