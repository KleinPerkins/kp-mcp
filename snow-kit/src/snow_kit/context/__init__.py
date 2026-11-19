"""Commit-pinned, bounded authoritative analytics context."""

from snow_kit.context.source import (
    GitHeadContextSource,
    build_context_source,
    context_source_status,
    validate_default_context_governance,
)

__all__ = [
    "GitHeadContextSource",
    "build_context_source",
    "context_source_status",
    "validate_default_context_governance",
]
