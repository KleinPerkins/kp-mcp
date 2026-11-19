"""Deterministic Snow intent, CLI help, and workflow safety tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from snow_kit.core.intents import alias_index, resolve_help
from snow_kit.registry import all_specs

SHOP_REVENUE_REQUEST = (
    "Show me a chart that plots Example Shop revenue as a stacked bar with customer "
    "membership as the bar segments (guest, standard, premium) for "
    "the last month"
)


@pytest.mark.parametrize(
    "query,operation",
    [
        ("search analytics context", "context.search"),
        ("find the authoritative metric definition", "context.search"),
        ("read this approved context section", "context.get"),
        ("describe this table", "catalog.describe_table"),
        ("find the GMV column", "catalog.search_columns"),
        ("analyze this SQL", "query.analyze"),
        ("run this read-only query", "query.execute"),
    ],
)
def test_required_simple_intents_rank_first(query: str, operation: str) -> None:
    result = resolve_help(query)
    assert result.status == "matched"
    assert result.recommended_first_operation == operation
    assert result.matches[0].operation == operation
    assert result.matches[0].reasons
    assert result.matches[0].required_args


def test_shop_request_recommends_conditional_context_first_workflow() -> None:
    result = resolve_help(SHOP_REVENUE_REQUEST)
    assert result.status == "workflow"
    assert result.recommended_first_operation == "context.search"
    workflow = result.workflow_recommendations[0]
    tools = [step.tool for step in workflow.steps if step.tool]
    assert tools == [
        "context_search",
        "context_get",
        "catalog_describe_table",
        "query_analyze",
        "query_execute",
    ]
    assert tools.index("context_get") < tools.index("query_execute")
    assert workflow.steps[1].prerequisites == [
        "A context_search result is semantically relevant to the requested analysis."
    ]
    assert any("irrelevant" in condition for condition in workflow.steps[1].stop_if)
    assert workflow.steps[0].stop_if == [
        "The context source is unavailable.",
        "No relevant governed result matches.",
    ]
    assert workflow.steps[2].stop_if == [
        "Any required analytical definition remains unresolved."
    ]
    assert workflow.steps[3].prerequisites == [
        "Relevant context identifies a fully qualified table candidate."
    ]
    assert workflow.steps[3].stop_if == [
        "Only database-wide or broad INFORMATION_SCHEMA exploration is possible."
    ]
    assert workflow.steps[4].optional is True
    assert workflow.steps[5].stop_if == [
        "The proposal requires USE, writes, guessed schema, or irrelevant context."
    ]
    assert workflow.steps[-1].kind == "external"
    assert workflow.steps[-1].tool is None
    assert "Snow-kit does not render charts." in workflow.limitations


def test_ambiguous_request_returns_reasons_but_no_executable_action() -> None:
    result = resolve_help("table")
    assert result.status == "ambiguous"
    assert result.recommended_first_operation is None
    assert len(result.matches) > 1
    assert all(match.reasons for match in result.matches)
    assert {
        action.kind
        for match in result.matches
        for action in match.suggested_next_actions
    } == {"clarify"}
    assert all(
        action.tool is None and action.operation is None
        for match in result.matches
        for action in match.suggested_next_actions
    )


def test_limit_one_still_uses_runner_up_to_detect_ambiguity() -> None:
    result = resolve_help("table", limit=1)
    assert result.status == "ambiguous"
    assert result.recommended_first_operation is None
    assert len(result.matches) == 1


def test_nonsense_returns_no_match_and_clarification() -> None:
    result = resolve_help("zzzqqq nonsense xyzzy")
    assert result.status == "no_match"
    assert result.matches == []
    assert result.recommended_first_operation is None
    assert result.clarification


def test_repeated_resolution_is_byte_deterministic() -> None:
    first = resolve_help(SHOP_REVENUE_REQUEST).model_dump_json()
    second = resolve_help(SHOP_REVENUE_REQUEST).model_dump_json()
    assert first == second


def test_help_never_invokes_operations_or_runtime_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("help crossed the metadata-only boundary")

    for spec in all_specs():
        monkeypatch.setattr(spec, "fn", forbidden)
    monkeypatch.setattr(
        "snow_kit.core.config.SnowKitConfig.from_env",
        forbidden,
    )
    monkeypatch.setattr(
        "snow_kit.context.source.build_context_source",
        forbidden,
    )
    assert resolve_help(SHOP_REVENUE_REQUEST).status == "workflow"


def test_hidden_write_is_not_recommended_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SNOW_KIT_ENABLE_WRITE", raising=False)
    result = resolve_help("execute snowflake write")
    assert all(match.operation != "query.execute_write" for match in result.matches)


def test_explicit_specs_cannot_bypass_write_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNOW_KIT_ENABLE_WRITE", "1")
    result = resolve_help(
        "execute snowflake write",
        specs=all_specs(),
        read_only=True,
    )
    assert all(match.operation != "query.execute_write" for match in result.matches)


def test_enabled_write_can_be_discovered_but_keeps_write_posture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNOW_KIT_ENABLE_WRITE", "1")
    result = resolve_help("execute snowflake write")
    match = next(
        match for match in result.matches if match.operation == "query.execute_write"
    )
    assert match.safety.posture == "write"
    assert match.safety.destructive is True
    assert [argument.name for argument in match.required_args] == [
        "query",
        "confirm_write",
        "justification",
    ]
    assert [argument.type for argument in match.required_args] == [
        "string",
        "boolean",
        "string",
    ]
    assert all(argument.required for argument in match.required_args)
    assert all(argument.description for argument in match.required_args)
    write_action = match.suggested_next_actions[-1]
    assert write_action.kind == "call_tool"
    assert write_action.tool == "query_execute_write"
    assert write_action.operation == "query.execute_write"
    assert any("confirm_write" in item for item in write_action.prerequisites)


def test_column_search_requires_scope_before_call() -> None:
    result = resolve_help("find the GMV column")
    assert result.matches[0].cli == "snow-kit catalog search_columns"
    actions = result.matches[0].suggested_next_actions
    assert actions[0].kind == "clarify"
    assert "database plus schema" in actions[0].instruction
    assert actions[1].tool == "catalog_search_columns"
    assert actions[1].prerequisites


def test_preview_help_preserves_sensitive_row_prerequisites() -> None:
    result = resolve_help("preview table rows")
    match = next(match for match in result.matches if match.operation == "catalog.preview_table")
    assert any("sensitive row values" in guard for guard in match.safety.guards)
    assert match.suggested_next_actions[0].kind == "clarify"
    assert match.suggested_next_actions[1].tool == "catalog_preview_table"
    assert any(
        "sensitive values" in item
        for item in match.suggested_next_actions[1].prerequisites
    )


def test_workflow_requires_an_analytical_measure_cue() -> None:
    positive = resolve_help("plot revenue by segment for the last quarter")
    assert positive.status == "workflow"
    assert positive.recommended_first_operation == "context.search"

    generic = resolve_help("plot approval rate by segment for last month")
    assert generic.status == "workflow"

    unrelated = resolve_help("plot lines by quarter")
    assert unrelated.status != "workflow"


def test_negated_action_never_returns_an_executable_recommendation() -> None:
    result = resolve_help("Please do not search analytics context")
    assert result.status == "no_match"
    assert result.recommended_first_operation is None
    assert result.matches == []
    assert "negates" in (result.clarification or "")


@pytest.mark.parametrize("source", ["spreadsheet", "CSV", "Google Sheet", "BigQuery"])
def test_explicit_non_snow_source_requests_clarification(source: str) -> None:
    result = resolve_help(f"Plot revenue by quarter from this {source}")
    assert result.status == "no_match"
    assert result.recommended_first_operation is None
    assert result.matches == []
    assert "non-Snow data source" in (result.clarification or "")


def test_query_execution_language_is_honest_about_bounds_and_session_state() -> None:
    result = resolve_help(SHOP_REVENUE_REQUEST)
    workflow = result.workflow_recommendations[0]
    assert any("max_rows caps returned rows" in item for item in workflow.limitations)
    assert any("USE changes shared session" in item for item in workflow.limitations)
    query_step = next(step for step in workflow.steps if step.tool == "query_execute")
    assert "SELECT/WITH" in query_step.instruction
    assert any("semantically relevant" in item for item in query_step.prerequisites)


def test_alias_index_contains_registry_approved_cues() -> None:
    index = alias_index()
    assert index["search analytics context"] == "context.search"
    assert index["find a column"] == "catalog.search_columns"
    assert index["run this read-only query"] == "query.execute"


def test_cli_help_returns_structured_output(capsys: pytest.CaptureFixture[str]) -> None:
    from snow_kit.cli import main

    assert main(["help", "describe", "this", "table", "--limit", "2"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "matched"
    assert payload["matches"][0]["operation"] == "catalog.describe_table"
    assert len(payload["matches"]) == 2


def test_cli_help_does_not_initialize_runtime_config(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from snow_kit.cli import main

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("CLI help crossed the metadata-only boundary")

    monkeypatch.setattr("snow_kit.core.config.SnowKitConfig.from_env", forbidden)
    monkeypatch.setattr("snow_kit.context.source.build_context_source", forbidden)
    for spec in all_specs():
        monkeypatch.setattr(spec, "fn", forbidden)
    assert main(["help", "search", "analytics", "context"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "matched"


def test_cli_help_no_match_and_invalid_input_exit_codes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from snow_kit.cli import main

    assert main(["help", "zzzqqq", "xyzzy"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "no_match"
    assert main(["help", "--limit", "0"]) == 2
    assert "invalid help request" in capsys.readouterr().err


def test_committed_intent_manifest_matches_generation(tmp_path: Path) -> None:
    from snow_kit.aliases_gen import _manifest_path, generate

    fresh = tmp_path / "INTENTS.md"
    generate(manifest_path=fresh)
    assert fresh.read_bytes() == _manifest_path().read_bytes()


def test_generated_help_schema_and_manifest_are_live_metadata() -> None:
    from snow_kit.mcp.metadata import HELP_TOOL_DESCRIPTION

    docs = Path(__file__).parents[1] / "docs" / "schemas"
    help_schema = json.loads((docs / "help.json").read_text(encoding="utf-8"))
    manifest = json.loads((docs / "_manifest.json").read_text(encoding="utf-8"))
    assert help_schema["description"] == HELP_TOOL_DESCRIPTION
    assert help_schema["inputSchema"]["required"] == ["intent"]
    assert help_schema["outputSchema"]["properties"]["workflow_recommendations"]
    assert manifest["meta_tools"] == {"help": "help.json"}


def test_generated_operation_schemas_use_live_descriptions() -> None:
    from snow_kit.mcp.metadata import tool_description

    schemas = Path(__file__).parents[1] / "docs" / "schemas"
    for spec in all_specs():
        schema = json.loads(
            (schemas / f"{spec.name}.json").read_text(encoding="utf-8")
        )
        assert schema["description"] == tool_description(spec)
    context_schema = json.loads(
        (schemas / "context.search.json").read_text(encoding="utf-8")
    )
    assert "search analytics context" in context_schema["description"]


def test_generated_cards_and_schemas_exactly_match_live_discovery() -> None:
    docs = Path(__file__).parents[1] / "docs"
    operation_names = {spec.name for spec in all_specs()}
    assert {path.stem for path in (docs / "cards").glob("*.md")} == {
        *operation_names,
        "help",
    }
    assert {
        path.stem
        for path in (docs / "schemas").glob("*.json")
        if path.name != "_manifest.json"
    } == {*operation_names, "help"}
    manifest = json.loads(
        (docs / "schemas" / "_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["ops"] == {
        name: f"{name}.json" for name in sorted(operation_names)
    }
    index_rows = [
        line
        for line in (docs / "INDEX.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| `")
    ]
    expected_rows = ["| `help` | read | [card](cards/help.md) |"]
    expected_rows.extend(
        (
            f"| `{spec.name}` | {spec.posture} | "
            f"[card](cards/{spec.name}.md) |"
        )
        for spec in sorted(all_specs(), key=lambda item: item.name)
    )
    assert index_rows == expected_rows
