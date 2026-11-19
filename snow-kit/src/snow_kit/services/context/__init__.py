"""Register bounded authoritative-context operations."""
from __future__ import annotations

from snow_kit.registry import OpSpec, register

from .core import context_get, context_search
from .models import ContextGetInput, ContextGetOutput, ContextSearchInput, ContextSearchOutput

_CONTEXT_ERRORS = [
    {
        "class": "Validation",
        "when": "The query, opaque document ID, revision, section, or limit is invalid",
        "retry": "Correct the input; use IDs/revisions returned by context.search",
    },
    {
        "class": "Unavailable",
        "when": "The configured checkout, pinned blob, or bounded local Git read is unavailable",
        "retry": "Repair setup/source state; never interpret as no matches",
    },
    {
        "class": "Timeout",
        "when": "Bounded local retrieval exceeds its time limit",
        "retry": "Narrow the approved corpus or search; no automatic retry",
    },
    {
        "class": "Unknown",
        "when": "The failure cannot be classified safely",
        "retry": "Escalate; do not retry automatically",
    },
]

register(
    OpSpec(
        name="context.search",
        fn=context_search,
        input_model=ContextSearchInput,
        output_model=ContextSearchOutput,
        posture="read",
        scopes=["local:approved-context"],
        perf={
            "source": "local Git HEAD",
            "max_results": 10,
            "network_fetch": False,
        },
        examples=[
            {
                "input": {"query": "Example Shop return rate", "limit": 5},
                "cli": "snow-kit context search --query 'Example Shop return rate' --limit 5",
            }
        ],
        aliases=[
            "search analytics context",
            "find the authoritative metric definition",
        ],
        keywords=["analytics", "context", "definitions", "tables"],
        errors=_CONTEXT_ERRORS,
    )
)

register(
    OpSpec(
        name="context.get",
        fn=context_get,
        input_model=ContextGetInput,
        output_model=ContextGetOutput,
        posture="read",
        scopes=["local:approved-context"],
        perf={
            "source": "local Git commit",
            "max_chars": 12_000,
            "network_fetch": False,
        },
        examples=[
            {
                "input": {
                    "document_id": "0123456789abcdef01234567",
                    "revision": "0123456789abcdef0123456789abcdef01234567",
                    "section": "Data Sources & Joins",
                },
                "cli": (
                    "snow-kit context get --document-id <id> --revision <sha> "
                    "--section 'Data Sources & Joins'"
                ),
            }
        ],
        aliases=["get analytics context", "read this approved context section"],
        keywords=["analytics", "context", "provenance"],
        errors=_CONTEXT_ERRORS,
    )
)
