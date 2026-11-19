"""Deterministic behavioral acceptance checks with MCP resources off and on."""
from __future__ import annotations

import pytest

from snow_kit.mcp.metadata import SERVER_INSTRUCTIONS, tool_description
from snow_kit.mcp.resources import guidance_documents
from snow_kit.registry import all_specs


def _assert_safe_agent_contract(text: str) -> None:
    normalized = " ".join(text.casefold().split())
    context_first = normalized.index("context_search")
    broad_discovery = normalized.index("broad information_schema")

    assert context_first < broad_discovery
    assert "call help first" in normalized
    assert "deterministic server-side" in normalized
    assert "model initially selects help remains model-dependent" in normalized
    assert "not semantic relevance" in normalized
    assert "known database plus schema or table candidate" in normalized
    assert "query_execute is read-only" in normalized
    assert "writes are hidden by default" in normalized
    assert "does not render charts" in normalized
    assert all(
        term in normalized
        for term in (
            "context evidence",
            "observed snowflake metadata",
            "query results",
            "inference",
        )
    )
    assert all(
        term in normalized
        for term in (
            "auth requires sign-in",
            "permission requires access correction",
            "timeout requires a narrower request",
        )
    )


@pytest.mark.parametrize("resources_enabled", [False, True])
def test_agent_behavior_is_safe_with_resources_disabled_or_enabled(
    resources_enabled: bool,
) -> None:
    visible_contract = [
        SERVER_INSTRUCTIONS,
        *(tool_description(spec) for spec in all_specs()),
    ]
    if resources_enabled:
        visible_contract.extend(document.content for document in guidance_documents())

    _assert_safe_agent_contract("\n".join(visible_contract))


def test_optional_resources_do_not_carry_mandatory_safety_invariant() -> None:
    assert "resources are optional references, not safety gates" in SERVER_INSTRUCTIONS
    _assert_safe_agent_contract(SERVER_INSTRUCTIONS)
