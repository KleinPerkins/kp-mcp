"""Registry surface tests for snow-kit."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from snow_kit.mcp.metadata import discovery_cue_suffix, discovery_cues
from snow_kit.registry import all_specs, get


def test_registered_ops_match_snowflake_surface() -> None:
    names = {spec.name for spec in all_specs()}
    assert names == {
        "query.execute",
        "query.analyze",
        "catalog.list_tables",
        "catalog.describe_table",
        "catalog.preview_table",
        "catalog.search_columns",
        "catalog.get_table_stats",
        "catalog.check_write_access",
        "context.get",
        "context.search",
        "query.execute_write",
    }
    assert get("query.execute").posture == "read"
    assert get("query.execute_write").posture == "write"
    assert get("query.execute_write").flag == "SNOW_KIT_ENABLE_WRITE"


def test_opspec_satisfies_protocol() -> None:
    assert all(spec.satisfies_opspec_like() for spec in all_specs())


def test_every_approved_alias_and_keyword_fits_live_discovery_budget() -> None:
    for spec in all_specs():
        expected: list[str] = []
        seen: set[str] = set()
        for cue in [*spec.aliases, *spec.keywords]:
            if cue.casefold() not in seen:
                seen.add(cue.casefold())
                expected.append(cue)
        assert discovery_cues(spec) == tuple(expected)
        suffix = discovery_cue_suffix(spec)
        assert suffix.startswith("Use this for:")
        assert len(expected) <= 6
        assert len(suffix) <= 240


def test_discovery_cues_dedupe_case_insensitively() -> None:
    spec = SimpleNamespace(
        name="catalog.example",
        aliases=["Find Rows", "find rows"],
        keywords=["ROWS", "rows"],
    )
    assert discovery_cues(spec) == ("Find Rows", "ROWS")


def test_discovery_cue_budgets_fail_instead_of_truncating() -> None:
    too_many = SimpleNamespace(
        name="catalog.too_many",
        aliases=[f"cue {index}" for index in range(7)],
        keywords=[],
    )
    too_long = SimpleNamespace(
        name="catalog.too_long",
        aliases=["x" * 230],
        keywords=[],
    )
    with pytest.raises(ValueError, match="live description budget"):
        discovery_cues(too_many)
    with pytest.raises(ValueError, match="240"):
        discovery_cue_suffix(too_long)
