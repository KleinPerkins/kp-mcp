"""Contract tests for the shared pure intent engine."""
from __future__ import annotations

from dataclasses import dataclass

from kp_mcp_bootstrap.intent import (
    IntentConfig,
    WorkflowCueGroup,
    WorkflowDefinition,
    WorkflowStep,
    build_alias_index,
    classify_resolution,
    operation_triggers,
    rank_operations,
    rank_workflows,
    tokenize,
)


@dataclass
class Spec:
    name: str
    aliases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    capability: str | None = None


CONFIG = IntentConfig(
    service_triggers={"files": ("document", "storage")},
    curated_aliases={"files.search": ("find a file",)},
    stopwords=frozenset({"a", "the"}),
    extra_strong_terms=lambda spec: (spec.capability,) if spec.capability else (),
)


def test_tokenize_is_normalized_and_stopword_aware() -> None:
    assert tokenize("Find THE Q4-file!", stopwords=CONFIG.stopwords) == [
        "find",
        "q4",
        "file",
    ]


def test_alias_index_is_first_registration_wins() -> None:
    specs = [
        Spec("files.search", aliases=("locate",), keywords=("lookup",)),
        Spec("folders.search", aliases=("locate",)),
    ]
    index = build_alias_index(specs)
    assert index["files search"] == "files.search"
    assert index["locate"] == "files.search"
    assert index["lookup"] == "files.search"


def test_operation_ranking_exposes_weighted_reasons() -> None:
    specs = [
        Spec("files.search", keywords=("lookup",), capability="content.find"),
        Spec("files.read"),
    ]
    match = rank_operations("find a file", specs, CONFIG)[0]
    assert match.operation == "files.search"
    assert match.score == 12.0
    assert match.matched_cues == ("find a file", "file", "find")
    assert [reason.kind for reason in match.reasons] == [
        "exact_phrase",
        "strong_token",
        "strong_token",
    ]


def test_operation_triggers_include_strong_and_weak_terms() -> None:
    triggers = operation_triggers(
        Spec("files.search", capability="content.find"),
        CONFIG,
    )
    assert {"files", "search", "content", "find", "document", "storage"} <= triggers


def test_rank_order_is_score_then_operation() -> None:
    specs = [Spec("z.read"), Spec("a.read")]
    assert [
        match.operation for match in rank_operations("read", specs, IntentConfig())
    ] == ["a.read", "z.read"]


def test_workflow_requires_configured_group_count() -> None:
    workflow = WorkflowDefinition(
        id="analytics",
        title="Analytics",
        summary="Context-first analytics.",
        cue_groups=(
            WorkflowCueGroup("measure", ("metric", "gmv")),
            WorkflowCueGroup("visual", ("chart", "plot")),
            WorkflowCueGroup("time", ("month", "quarter")),
        ),
        minimum_groups=2,
        steps=(
            WorkflowStep(
                id="discover",
                kind="call_tool",
                instruction="Discover context.",
                operation="context.search",
            ),
        ),
    )
    assert rank_workflows("metric definition", [workflow]) == []
    match = rank_workflows("plot GMV for the month", [workflow])[0]
    assert match.workflow_id == "analytics"
    assert match.score == 6.0
    assert match.matched_cues == ("gmv", "plot", "month")


def test_workflow_requires_named_groups_when_configured() -> None:
    workflow = WorkflowDefinition(
        id="analytics",
        title="Analytics",
        summary="Context-first analytics.",
        cue_groups=(
            WorkflowCueGroup("domain", ("gmv", "revenue")),
            WorkflowCueGroup("visual", ("chart", "plot")),
            WorkflowCueGroup("time", ("month", "quarter")),
        ),
        minimum_groups=2,
        required_groups=("domain",),
        steps=(
            WorkflowStep(
                id="discover",
                kind="call_tool",
                instruction="Discover context.",
                operation="context.search",
            ),
        ),
    )
    assert rank_workflows("plot by quarter", [workflow]) == []
    assert rank_workflows("plot revenue by quarter", [workflow])[0].workflow_id == (
        "analytics"
    )


def test_resolution_precedence_and_ambiguity() -> None:
    specs = [Spec("a.read"), Spec("b.read")]
    matches = rank_operations("read", specs, IntentConfig())
    ambiguous = classify_resolution(
        "read",
        matches,
        ambiguous_clarification="Clarify.",
    )
    assert ambiguous.status == "ambiguous"
    assert ambiguous.recommended_first_operation is None

    workflow = WorkflowDefinition(
        id="flow",
        title="Flow",
        summary="Flow.",
        cue_groups=(WorkflowCueGroup("read", ("read",)),),
        minimum_groups=1,
        steps=(
            WorkflowStep(
                id="first",
                kind="call_tool",
                instruction="Start.",
                operation="context.search",
            ),
        ),
    )
    workflow_matches = rank_workflows("read", [workflow])
    resolved = classify_resolution("read", matches, workflow_matches)
    assert resolved.status == "workflow"
    assert resolved.recommended_first_operation == "context.search"


def test_no_match_has_clear_status() -> None:
    resolved = classify_resolution(
        "nonsense",
        [],
        no_match_clarification="Describe the task.",
    )
    assert resolved.status == "no_match"
    assert resolved.clarification == "Describe the task."
