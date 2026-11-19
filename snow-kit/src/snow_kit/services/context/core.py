"""Core operations for authoritative analytics context retrieval."""
from __future__ import annotations

from snow_kit.context import build_context_source
from snow_kit.core.errors import Unavailable
from snow_kit.core.normalize import Meta

from .models import (
    ContextGetData,
    ContextGetInput,
    ContextGetOutput,
    ContextSearchData,
    ContextSearchInput,
    ContextSearchOutput,
)


def context_search(inp: ContextSearchInput) -> ContextSearchOutput:
    """Search configured governed Markdown at one exact local Git revision."""
    source = build_context_source()
    if source is None:
        raise Unavailable(
            "No authoritative context source is configured. "
            "Run `snow-kit setup --context-repo <checkout>`.",
            op="context.search",
        )
    result = source.search(inp.query, limit=inp.limit)
    warnings = result.pop("warnings")
    return ContextSearchOutput(
        data=ContextSearchData.model_validate(result),
        warnings=warnings,
        meta=Meta(op="context.search"),
    )


def context_get(inp: ContextGetInput) -> ContextGetOutput:
    """Read one bounded approved document or section from its pinned revision."""
    source = build_context_source()
    if source is None:
        raise Unavailable(
            "No authoritative context source is configured. "
            "Run `snow-kit setup --context-repo <checkout>`.",
            op="context.get",
        )
    result = source.get(
        inp.document_id,
        inp.revision,
        section=inp.section,
        max_chars=inp.max_chars,
    )
    warnings = result.pop("warnings")
    return ContextGetOutput(
        data=ContextGetData.model_validate(result),
        warnings=warnings,
        meta=Meta(op="context.get"),
    )
