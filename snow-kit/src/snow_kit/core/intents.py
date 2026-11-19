"""Snow-owned intent vocabulary, conditional workflows, and help presentation."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from kp_mcp_bootstrap.docgen import mcp_tool_name
from kp_mcp_bootstrap.intent import (
    IntentConfig,
    IntentResolution,
    MatchReason,
    RankedIntentMatch,
    WorkflowCueGroup,
    WorkflowDefinition,
    WorkflowMatch,
    WorkflowStep,
    build_alias_index,
    classify_resolution,
    operation_triggers,
    rank_operations,
    rank_workflows,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from snow_kit.core.flags import is_flag_enabled
from snow_kit.registry import OpSpec, all_specs, get

_STOPWORDS = frozenset(
    "a an the how do i to my in of for with on and or is it me can please "
    "this that from into".split()
)
_NEGATED_ACTION_RE = re.compile(
    r"\b(?:do\s+not|don['’]?t|never)\s+"
    r"(?:analyze|describe|execute|find|inspect|preview|query|read|retrieve|run|search)\b",
    re.IGNORECASE,
)
_NON_SNOW_SOURCE_RE = re.compile(
    r"\b(?:bigquery|csv(?:\s+file)?|databricks|excel|google\s+sheets?|"
    r"redshift|spreadsheet)\b",
    re.IGNORECASE,
)

_SERVICE_TRIGGERS: dict[str, tuple[str, ...]] = {
    "context": (
        "analytics",
        "authoritative",
        "business",
        "context",
        "definition",
        "governed",
        "metric",
        "provenance",
    ),
    "catalog": (
        "catalog",
        "column",
        "columns",
        "database",
        "metadata",
        "schema",
        "table",
        "tables",
    ),
    "query": (
        "analyze",
        "execute",
        "explain",
        "query",
        "read",
        "snowflake",
        "sql",
    ),
}

_CURATED_ALIASES: dict[str, tuple[str, ...]] = {
    "context.search": (
        "search analytics context",
        "find the authoritative metric definition",
        "discover governed analytics definitions",
    ),
    "context.get": (
        "read this approved context section",
        "retrieve governed context",
    ),
    "catalog.describe_table": (
        "describe this table",
        "inspect table columns",
    ),
    "catalog.search_columns": (
        "find a column",
        "search scoped column metadata",
    ),
    "query.analyze": (
        "analyze this sql",
        "explain this query",
    ),
    "query.execute": (
        "run this read-only query",
        "execute bounded select sql",
    ),
}

_INTENT_CONFIG = IntentConfig(
    service_triggers=_SERVICE_TRIGGERS,
    curated_aliases=_CURATED_ALIASES,
    stopwords=_STOPWORDS,
)

_ANALYTICS_WORKFLOW = WorkflowDefinition(
    id="analytics.context_first_query",
    title="Context-first analytical query",
    summary=(
        "Resolve governed definitions and narrow metadata scope before proposing "
        "bounded read-only analytical SQL."
    ),
    cue_groups=(
        WorkflowCueGroup(
            "analytical_measure",
            ("metric", "measure", "gmv", "revenue", "volume", "rate"),
        ),
        WorkflowCueGroup(
            "breakdown_or_visualization",
            (
                "chart",
                "plot",
                "bar",
                "line",
                "stacked",
                "segment",
                "segments",
                "breakdown",
                "group",
                "grouped",
            ),
        ),
        WorkflowCueGroup(
            "time_definition",
            (
                "date",
                "day",
                "week",
                "month",
                "quarter",
                "year",
                "window",
                "period",
            ),
        ),
    ),
    minimum_groups=2,
    required_groups=("analytical_measure",),
    steps=(
        WorkflowStep(
            id="discover_context",
            kind="call_tool",
            operation="context.search",
            tool="context_search",
            instruction=(
                "Search the configured governed analytics corpus for the metric, "
                "segment, date-window, timezone, and grain definitions."
            ),
            prerequisites=("A configured governed context source is available.",),
            stop_if=(
                "The context source is unavailable.",
                "No relevant governed result matches.",
            ),
        ),
        WorkflowStep(
            id="read_context",
            kind="call_tool",
            operation="context.get",
            tool="context_get",
            instruction=(
                "Read only the selected relevant section using the opaque "
                "document_id and exact revision returned by context_search."
            ),
            prerequisites=(
                "A context_search result is semantically relevant to the requested analysis.",
            ),
            stop_if=(
                "The result is stale, ambiguous, irrelevant, or outside approved paths.",
            ),
        ),
        WorkflowStep(
            id="clarify_definitions",
            kind="clarify",
            instruction=(
                "Clarify every unresolved metric, segment, date-window, timezone, "
                "and chart-grain definition before metadata inspection."
            ),
            prerequisites=(
                "Treat provenance validity and semantic relevance as separate checks.",
            ),
            stop_if=("Any required analytical definition remains unresolved.",),
        ),
        WorkflowStep(
            id="inspect_catalog",
            kind="call_tool",
            operation="catalog.describe_table",
            tool="catalog_describe_table",
            instruction=(
                "Inspect a fully qualified table candidate narrowly; use "
                "catalog_search_columns only within a known database plus schema."
            ),
            prerequisites=(
                "Relevant context identifies a fully qualified table candidate.",
            ),
            stop_if=(
                "Only database-wide or broad INFORMATION_SCHEMA exploration is possible.",
            ),
        ),
        WorkflowStep(
            id="analyze_query",
            kind="call_tool",
            operation="query.analyze",
            tool="query_analyze",
            instruction="Optionally analyze the proposed bounded SELECT/WITH statement.",
            prerequisites=(
                "The SQL uses confirmed definitions and observed catalog metadata.",
            ),
            optional=True,
        ),
        WorkflowStep(
            id="execute_query",
            kind="call_tool",
            operation="query.execute",
            tool="query_execute",
            instruction=(
                "Execute bounded read-only SELECT/WITH SQL and return chart-ready rows."
            ),
            prerequisites=(
                "Context references are provenance-valid and semantically relevant.",
                "Catalog scope, joins, finite time predicate, timezone, and grain are confirmed.",
                "SQL validation, permissions, and returned-row limits all pass.",
            ),
            stop_if=(
                "The proposal requires USE, writes, guessed schema, or irrelevant context.",
            ),
        ),
        WorkflowStep(
            id="visualize_rows",
            kind="external",
            instruction=(
                "Hand chart-ready rows to a caller-provided visualization surface."
            ),
            prerequisites=("Query results are complete enough for the requested chart.",),
        ),
    ),
    limitations=(
        "Snow-kit does not render charts.",
        "max_rows caps returned rows; it does not reduce warehouse scanning.",
        "USE changes shared session context and is not recommended by this workflow.",
    ),
)

_WORKFLOWS = (_ANALYTICS_WORKFLOW,)

_SAFETY_INVARIANTS = (
    "Help and resolution perform no Snowflake query, context retrieval, or write.",
    "Write tools remain hidden unless the existing gate exposes them.",
    "Context warning/strict modes and context-reference validation remain authoritative.",
    "A provenance-valid but irrelevant context document is not analytical evidence.",
    "Missing context never authorizes broad INFORMATION_SCHEMA exploration.",
    "SQL validation, scoped catalog inspection, permissions, and row limits still apply.",
)


class HelpInput(BaseModel):
    """Validated input for CLI and MCP help."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(
        min_length=1,
        max_length=1_000,
        description="Complete plain-English task to route.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum ranked operation matches to return.",
    )

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, value: str) -> str:
        """Trim intent and reject whitespace-only requests."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("intent must contain non-whitespace text")
        return normalized


class HelpReason(BaseModel):
    """One weighted cue explaining a score."""

    kind: str
    cue: str
    weight: float


class RequiredArgument(BaseModel):
    """One required argument for a recommended operation."""

    name: str
    type: str
    description: str
    required: bool = True


class SafetyPosture(BaseModel):
    """Live posture and conservative MCP hints for an operation."""

    posture: str
    read_only: bool
    destructive: bool
    idempotent: bool | None
    open_world: bool
    guards: list[str]


class HelpAction(BaseModel):
    """A conditional next action; help never executes it."""

    kind: Literal["clarify", "call_tool", "external"]
    instruction: str
    tool: str | None = None
    operation: str | None = None
    prerequisites: list[str] = Field(default_factory=list)
    stop_if: list[str] = Field(default_factory=list)
    optional: bool = False


class HelpMatch(BaseModel):
    """Enriched ranked operation metadata."""

    operation: str
    tool: str
    cli: str
    summary: str
    score: float
    matched_cues: list[str]
    reasons: list[HelpReason]
    required_args: list[RequiredArgument]
    safety: SafetyPosture
    suggested_next_actions: list[HelpAction]


class WorkflowRecommendation(BaseModel):
    """One conditional multi-step workflow recommendation."""

    workflow_id: str
    title: str
    summary: str
    score: float
    matched_cues: list[str]
    reasons: list[HelpReason]
    steps: list[HelpAction]
    limitations: list[str]


class HelpOutput(BaseModel):
    """Structured deterministic help response."""

    intent: str
    status: Literal["matched", "ambiguous", "workflow", "no_match"]
    deterministic: bool = True
    recommended_first_operation: str | None = None
    matches: list[HelpMatch]
    workflow_recommendations: list[WorkflowRecommendation]
    clarification: str | None = None
    safety_invariants: list[str]


def curated_aliases(operation: str) -> tuple[str, ...]:
    """Return Snow-owned curated phrases for one operation."""
    return _CURATED_ALIASES.get(operation, ())


def alias_index(specs: Sequence[OpSpec] | None = None) -> dict[str, str]:
    """Return first-wins names, aliases, and keyword mappings."""
    return build_alias_index(list(specs) if specs is not None else all_specs())


def op_triggers(spec: OpSpec) -> set[str]:
    """Return all configured triggers for one Snow operation."""
    return operation_triggers(spec, _INTENT_CONFIG)


def workflow_definitions() -> tuple[WorkflowDefinition, ...]:
    """Return immutable configured workflow definitions."""
    return _WORKFLOWS


def visible_specs(
    specs: Sequence[OpSpec] | None = None,
    *,
    read_only: bool = False,
) -> list[OpSpec]:
    """Apply Snow's existing write visibility policy for every discovery surface."""
    candidates = list(specs) if specs is not None else all_specs()
    return [
        spec
        for spec in candidates
        if not (
            spec.posture in {"write", "destructive"}
            and (read_only or not is_flag_enabled(getattr(spec, "flag", None)))
        )
    ]


def safety_hints(spec: OpSpec) -> dict[str, bool | None]:
    """Return the canonical conservative MCP hint values for an operation."""
    session_changing = spec.name == "query.execute"
    read_only = spec.posture == "read" and not session_changing
    mutating = spec.posture in {"write", "destructive"}
    return {
        "read_only": read_only,
        "destructive": mutating,
        "idempotent": True if read_only else None,
        "open_world": True,
    }


def resolve_help(
    intent: str,
    *,
    limit: int = 5,
    specs: Sequence[OpSpec] | None = None,
    read_only: bool = False,
) -> HelpOutput:
    """Resolve intent from registry metadata without invoking any operation."""
    validated = HelpInput(intent=intent, limit=limit)
    if _NEGATED_ACTION_RE.search(validated.intent):
        return HelpOutput(
            intent=validated.intent,
            status="no_match",
            recommended_first_operation=None,
            matches=[],
            workflow_recommendations=[],
            clarification=(
                "The request negates a Snow operation, so no tool is recommended. "
                "State the positive task you want routed."
            ),
            safety_invariants=list(_SAFETY_INVARIANTS),
        )
    if _NON_SNOW_SOURCE_RE.search(validated.intent):
        return HelpOutput(
            intent=validated.intent,
            status="no_match",
            recommended_first_operation=None,
            matches=[],
            workflow_recommendations=[],
            clarification=(
                "The request names a non-Snow data source. Route it to that source's "
                "tooling, or clarify that the data is available in Snowflake."
            ),
            safety_invariants=list(_SAFETY_INVARIANTS),
        )
    candidates = visible_specs(specs, read_only=read_only)
    ranked = rank_operations(
        validated.intent,
        candidates,
        _INTENT_CONFIG,
        limit=max(validated.limit, 2),
    )
    workflow_matches = rank_workflows(
        validated.intent,
        _WORKFLOWS,
        stopwords=_STOPWORDS,
        limit=3,
    )
    resolution = classify_resolution(
        validated.intent,
        ranked,
        workflow_matches,
        minimum_score=2.0,
        ambiguity_margin=0.5,
        ambiguous_clarification=(
            "Clarify whether the task is governed context discovery, bounded "
            "catalog inspection, SQL analysis, or read-only execution."
        ),
        no_match_clarification=(
            "Describe whether you need governed context discovery, a known table "
            "or column inspected, SQL analyzed, or bounded read-only SQL executed."
        ),
    )
    executable = resolution.status == "matched"
    return HelpOutput(
        intent=validated.intent,
        status=resolution.status,
        recommended_first_operation=resolution.recommended_first_operation,
        matches=[
            _help_match(match, executable=executable)
            for match in resolution.matches[: validated.limit]
        ],
        workflow_recommendations=[
            _workflow_recommendation(match) for match in resolution.workflows
        ],
        clarification=resolution.clarification,
        safety_invariants=list(_SAFETY_INVARIANTS),
    )


def _help_match(match: RankedIntentMatch, *, executable: bool) -> HelpMatch:
    spec = get(match.operation)
    hints = safety_hints(spec)
    return HelpMatch(
        operation=spec.name,
        tool=mcp_tool_name(spec.name),
        cli=f"snow-kit {_cli_form(spec.name)}",
        summary=_first_line(spec.fn.__doc__),
        score=match.score,
        matched_cues=list(match.matched_cues),
        reasons=[_help_reason(reason) for reason in match.reasons],
        required_args=_required_arguments(spec),
        safety=SafetyPosture(
            posture=spec.posture,
            read_only=bool(hints["read_only"]),
            destructive=bool(hints["destructive"]),
            idempotent=hints["idempotent"],
            open_world=bool(hints["open_world"]),
            guards=_guards(spec),
        ),
        suggested_next_actions=_next_actions(spec, executable=executable),
    )


def _workflow_recommendation(match: WorkflowMatch) -> WorkflowRecommendation:
    return WorkflowRecommendation(
        workflow_id=match.workflow_id,
        title=match.title,
        summary=match.summary,
        score=match.score,
        matched_cues=list(match.matched_cues),
        reasons=[_help_reason(reason) for reason in match.reasons],
        steps=[_workflow_action(step) for step in match.steps],
        limitations=list(match.limitations),
    )


def _help_reason(reason: MatchReason) -> HelpReason:
    return HelpReason(kind=reason.kind, cue=reason.cue, weight=reason.weight)


def _workflow_action(step: WorkflowStep) -> HelpAction:
    return HelpAction(
        kind=step.kind,  # type: ignore[arg-type]
        instruction=step.instruction,
        tool=step.tool,
        operation=step.operation,
        prerequisites=list(step.prerequisites),
        stop_if=list(step.stop_if),
        optional=step.optional,
    )


def _required_arguments(spec: OpSpec) -> list[RequiredArgument]:
    schema = spec.input_model.model_json_schema()
    properties = schema.get("properties", {})
    required_names = list(schema.get("required", []))
    if spec.name == "query.execute_write":
        for runtime_required in ("confirm_write", "justification"):
            if runtime_required not in required_names:
                required_names.append(runtime_required)
    return [
        RequiredArgument(
            name=name,
            type=_schema_type(properties.get(name, {})),
            description=str(
                properties.get(name, {}).get(
                    "description",
                    properties.get(name, {}).get("title", name),
                )
            ),
        )
        for name in required_names
    ]


def _schema_type(field_schema: dict[str, Any]) -> str:
    if "type" in field_schema:
        return str(field_schema["type"])
    non_null = [
        branch.get("type", "object")
        for branch in field_schema.get("anyOf", [])
        if branch.get("type") != "null"
    ]
    return str(non_null[0]) if non_null else "object"


def _next_actions(spec: OpSpec, *, executable: bool) -> list[HelpAction]:
    if not executable:
        return [
            HelpAction(
                kind="clarify",
                instruction=(
                    "Clarify the intended operation before calling any Snow tool."
                ),
            )
        ]
    if spec.name == "context.search":
        return [
            HelpAction(
                kind="call_tool",
                tool="context_search",
                operation=spec.name,
                instruction="Search the configured governed context corpus.",
                prerequisites=["A governed context source is configured."],
            )
        ]
    if spec.name == "context.get":
        return [
            HelpAction(
                kind="clarify",
                instruction=(
                    "Select a semantically relevant context_search result first."
                ),
            ),
            HelpAction(
                kind="call_tool",
                tool="context_get",
                operation=spec.name,
                instruction="Read the bounded approved section.",
                prerequisites=[
                    "Use the opaque document_id and exact revision from context_search."
                ],
            ),
        ]
    if spec.name == "catalog.search_columns":
        return [
            HelpAction(
                kind="clarify",
                instruction=(
                    "Establish a known database plus schema or a table candidate."
                ),
                stop_if=[
                    "Only database-wide or broad INFORMATION_SCHEMA discovery is possible."
                ],
            ),
            HelpAction(
                kind="call_tool",
                tool="catalog_search_columns",
                operation=spec.name,
                instruction="Search column metadata only within that narrow scope.",
                prerequisites=["Governed context or operator input established the scope."],
            ),
        ]
    if spec.name == "catalog.preview_table":
        return [
            HelpAction(
                kind="clarify",
                instruction=(
                    "Describe the table first and confirm that previewing row values "
                    "is necessary."
                ),
            ),
            HelpAction(
                kind="call_tool",
                tool="catalog_preview_table",
                operation=spec.name,
                instruction="Preview the smallest useful number of rows.",
                prerequisites=[
                    "catalog_describe_table confirmed the table and expected columns.",
                    "The caller accepts that returned rows can contain sensitive values.",
                ],
            ),
        ]
    if spec.name == "query.execute":
        return [
            HelpAction(
                kind="clarify",
                instruction=(
                    "Confirm relevant governed definitions, catalog scope, finite "
                    "time predicate, timezone, and grain."
                ),
            ),
            HelpAction(
                kind="call_tool",
                tool="query_execute",
                operation=spec.name,
                instruction="Execute validated bounded SELECT/WITH SQL.",
                prerequisites=[
                    "Context references are provenance-valid and semantically relevant.",
                    "SQL validation, permissions, and returned-row limits pass.",
                ],
                stop_if=["The request requires USE, guessed schema, or a write."],
            ),
        ]
    if spec.name == "query.execute_write":
        return [
            HelpAction(
                kind="clarify",
                instruction=(
                    "Confirm the write is necessary and provide an explicit audit "
                    "justification."
                ),
            ),
            HelpAction(
                kind="call_tool",
                tool="query_execute_write",
                operation=spec.name,
                instruction="Execute one policy-approved write statement.",
                prerequisites=[
                    "SNOW_KIT_ENABLE_WRITE=1 explicitly exposes the write tool.",
                    "confirm_write is true and justification is non-empty.",
                    "Policy validation and grant preflight both pass.",
                ],
            ),
        ]
    return [
        HelpAction(
            kind="call_tool",
            tool=mcp_tool_name(spec.name),
            operation=spec.name,
            instruction=f"Call {mcp_tool_name(spec.name)} with its required arguments.",
            prerequisites=["Existing server-side safety and permission checks still apply."],
        )
    ]


def _guards(spec: OpSpec) -> list[str]:
    guards = ["Help does not invoke this operation."]
    if spec.name.startswith("context."):
        guards.append("Configured approved-source bounds and redaction remain authoritative.")
    if spec.name.startswith("catalog."):
        guards.append("Use governed, narrowly scoped database/schema/table context.")
    if spec.name == "catalog.preview_table":
        guards.append(
            "Describe the table first; previews can return sensitive row values."
        )
    if spec.name in {"query.analyze", "query.execute"}:
        guards.extend(
            [
                "Relevant context and observed catalog metadata must ground analytical SQL.",
                "SQL validation and permissions remain authoritative.",
            ]
        )
    if spec.name == "query.execute":
        guards.append("max_rows limits returned rows, not warehouse scanning.")
    if spec.posture in {"write", "destructive"}:
        guards.append(
            "Write enablement, explicit confirmation, non-empty justification, policy "
            "validation, and grant preflight remain authoritative."
        )
    return guards


def _cli_form(operation: str) -> str:
    service, _, name = operation.partition(".")
    return f"{service} {name}"


def _first_line(doc: str | None) -> str:
    return doc.strip().splitlines()[0] if doc else ""
