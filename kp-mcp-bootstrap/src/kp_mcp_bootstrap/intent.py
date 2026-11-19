"""Pure, domain-neutral intent ranking and workflow recommendation contracts."""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol


class IntentSpecLike(Protocol):
    """Minimal operation metadata consumed by the intent engine."""

    name: str
    aliases: Sequence[str]
    keywords: Sequence[str]


@dataclass(frozen=True)
class RankingWeights:
    """Deterministic operation-ranking weights."""

    exact_phrase: float = 10.0
    strong_token: float = 1.0
    weak_token: float = 0.5
    terminal_verb: float = 1.5


@dataclass(frozen=True)
class IntentConfig:
    """Injected vocabulary and scoring configuration for one kit."""

    service_triggers: Mapping[str, Sequence[str]] = field(default_factory=dict)
    curated_aliases: Mapping[str, Sequence[str]] = field(default_factory=dict)
    stopwords: frozenset[str] = frozenset()
    weights: RankingWeights = RankingWeights()
    extra_strong_terms: Callable[[IntentSpecLike], Iterable[str]] | None = None


@dataclass(frozen=True)
class MatchReason:
    """One auditable contribution to a deterministic score."""

    kind: str
    cue: str
    weight: float


@dataclass(frozen=True)
class RankedIntentMatch:
    """One ranked operation match."""

    operation: str
    score: float
    matched_cues: tuple[str, ...]
    reasons: tuple[MatchReason, ...]


@dataclass(frozen=True)
class WorkflowCueGroup:
    """A semantic cue group used to qualify a workflow."""

    name: str
    cues: tuple[str, ...]
    weight: float = 2.0


@dataclass(frozen=True)
class WorkflowStep:
    """One conditional recommendation; it never executes an operation."""

    id: str
    kind: str
    instruction: str
    operation: str | None = None
    tool: str | None = None
    prerequisites: tuple[str, ...] = ()
    stop_if: tuple[str, ...] = ()
    optional: bool = False


@dataclass(frozen=True)
class WorkflowDefinition:
    """Configured multi-step workflow matched by semantic cue groups."""

    id: str
    title: str
    summary: str
    cue_groups: tuple[WorkflowCueGroup, ...]
    minimum_groups: int
    steps: tuple[WorkflowStep, ...]
    required_groups: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowMatch:
    """One ranked workflow recommendation."""

    workflow_id: str
    title: str
    summary: str
    score: float
    matched_cues: tuple[str, ...]
    reasons: tuple[MatchReason, ...]
    steps: tuple[WorkflowStep, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class IntentResolution:
    """Transport-neutral routing result."""

    query: str
    status: str
    matches: tuple[RankedIntentMatch, ...]
    workflows: tuple[WorkflowMatch, ...]
    recommended_first_operation: str | None
    clarification: str | None


def tokenize(text: str, *, stopwords: frozenset[str] = frozenset()) -> list[str]:
    """Return deterministic lowercase alphanumeric tokens."""
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 2 and token not in stopwords
    ]


def build_alias_index(specs: Sequence[IntentSpecLike]) -> dict[str, str]:
    """Map normalized names, CLI forms, aliases, and keywords to operations."""
    output: dict[str, str] = {}

    def add(value: str, operation: str) -> None:
        key = value.strip().lower()
        if key and key not in output:
            output[key] = operation

    for spec in specs:
        add(spec.name, spec.name)
        add(spec.name.replace(".", " "), spec.name)
        for value in (*spec.aliases, *spec.keywords):
            add(str(value), spec.name)
    return output


def strong_triggers(spec: IntentSpecLike, config: IntentConfig) -> set[str]:
    """Return operation-discriminating tokens."""
    triggers = {token for token in re.split(r"[._]", spec.name.lower()) if token}
    if config.extra_strong_terms is not None:
        for value in config.extra_strong_terms(spec):
            triggers.update(
                token for token in re.split(r"[._]", str(value).lower()) if token
            )
    explicit = (
        *config.curated_aliases.get(spec.name, ()),
        *spec.aliases,
        *spec.keywords,
    )
    for phrase in explicit:
        triggers.update(tokenize(str(phrase), stopwords=config.stopwords))
    return triggers


def weak_triggers(spec: IntentSpecLike, config: IntentConfig) -> set[str]:
    """Return service-wide synonym tokens that carry lower weight."""
    service = spec.name.split(".", 1)[0]
    return set(config.service_triggers.get(service, ())) - strong_triggers(spec, config)


def operation_triggers(spec: IntentSpecLike, config: IntentConfig) -> set[str]:
    """Return all strong and weak trigger terms for a manifest."""
    return strong_triggers(spec, config) | weak_triggers(spec, config)


def rank_operations(
    query: str,
    specs: Sequence[IntentSpecLike],
    config: IntentConfig,
    *,
    limit: int = 5,
) -> list[RankedIntentMatch]:
    """Rank operations using configured exact, strong, weak, and verb cues."""
    normalized = query.strip().lower()
    query_tokens = set(tokenize(normalized, stopwords=config.stopwords))
    results: list[RankedIntentMatch] = []

    for spec in specs:
        phrases = {spec.name.lower(), spec.name.replace(".", " ").lower()}
        phrases.update(
            phrase.strip().lower()
            for phrase in config.curated_aliases.get(spec.name, ())
        )
        phrases.update(str(alias).strip().lower() for alias in spec.aliases)

        score = 0.0
        matched: list[str] = []
        reasons: list[MatchReason] = []
        if normalized and normalized in phrases:
            score += config.weights.exact_phrase
            matched.append(normalized)
            reasons.append(
                MatchReason("exact_phrase", normalized, config.weights.exact_phrase)
            )

        strong_hits = query_tokens & strong_triggers(spec, config)
        weak_hits = (query_tokens & weak_triggers(spec, config)) - strong_hits
        for cue in sorted(strong_hits):
            score += config.weights.strong_token
            matched.append(cue)
            reasons.append(
                MatchReason("strong_token", cue, config.weights.strong_token)
            )
        for cue in sorted(weak_hits):
            score += config.weights.weak_token
            matched.append(cue)
            reasons.append(MatchReason("weak_token", cue, config.weights.weak_token))

        terminal_verb = re.split(r"[._]", spec.name.lower())[-1]
        if terminal_verb in query_tokens:
            score += config.weights.terminal_verb
            reasons.append(
                MatchReason(
                    "terminal_verb",
                    terminal_verb,
                    config.weights.terminal_verb,
                )
            )

        if score > 0:
            results.append(
                RankedIntentMatch(
                    operation=spec.name,
                    score=score,
                    matched_cues=tuple(dict.fromkeys(matched)),
                    reasons=tuple(reasons),
                )
            )

    results.sort(key=lambda match: (-match.score, match.operation))
    return results[:limit]


def rank_workflows(
    query: str,
    definitions: Sequence[WorkflowDefinition],
    *,
    stopwords: frozenset[str] = frozenset(),
    limit: int = 3,
) -> list[WorkflowMatch]:
    """Rank configured workflows by semantic cue-group coverage."""
    query_tokens = set(tokenize(query, stopwords=stopwords))
    results: list[WorkflowMatch] = []

    for definition in definitions:
        matched_groups = 0
        matched_group_names: set[str] = set()
        matched_cues: list[str] = []
        reasons: list[MatchReason] = []
        score = 0.0
        for group in definition.cue_groups:
            group_hits = [
                cue
                for cue in group.cues
                if (cue_tokens := set(tokenize(cue, stopwords=stopwords)))
                and cue_tokens <= query_tokens
            ]
            if not group_hits:
                continue
            matched_groups += 1
            matched_group_names.add(group.name)
            score += group.weight
            matched_cues.extend(group_hits)
            reasons.append(
                MatchReason(
                    kind=f"workflow_group:{group.name}",
                    cue=group_hits[0],
                    weight=group.weight,
                )
            )
        if (
            matched_groups >= definition.minimum_groups
            and set(definition.required_groups) <= matched_group_names
        ):
            results.append(
                WorkflowMatch(
                    workflow_id=definition.id,
                    title=definition.title,
                    summary=definition.summary,
                    score=score,
                    matched_cues=tuple(dict.fromkeys(matched_cues)),
                    reasons=tuple(reasons),
                    steps=definition.steps,
                    limitations=definition.limitations,
                )
            )

    results.sort(key=lambda match: (-match.score, match.workflow_id))
    return results[:limit]


def classify_resolution(
    query: str,
    matches: Sequence[RankedIntentMatch],
    workflows: Sequence[WorkflowMatch] = (),
    *,
    minimum_score: float = 2.0,
    ambiguity_margin: float = 0.5,
    ambiguous_clarification: str | None = None,
    no_match_clarification: str | None = None,
) -> IntentResolution:
    """Classify ranked results without selecting or executing a tool."""
    match_tuple = tuple(matches)
    workflow_tuple = tuple(workflows)
    if workflow_tuple:
        first_operation = next(
            (
                step.operation
                for step in workflow_tuple[0].steps
                if step.operation is not None
            ),
            None,
        )
        return IntentResolution(
            query=query,
            status="workflow",
            matches=match_tuple,
            workflows=workflow_tuple,
            recommended_first_operation=first_operation,
            clarification=None,
        )
    if not match_tuple:
        return IntentResolution(
            query=query,
            status="no_match",
            matches=(),
            workflows=(),
            recommended_first_operation=None,
            clarification=no_match_clarification,
        )

    top = match_tuple[0]
    exact = any(reason.kind == "exact_phrase" for reason in top.reasons)
    margin = (
        top.score - match_tuple[1].score
        if len(match_tuple) > 1
        else float("inf")
    )
    if top.score >= minimum_score and (exact or margin > ambiguity_margin):
        return IntentResolution(
            query=query,
            status="matched",
            matches=match_tuple,
            workflows=(),
            recommended_first_operation=top.operation,
            clarification=None,
        )
    return IntentResolution(
        query=query,
        status="ambiguous",
        matches=match_tuple,
        workflows=(),
        recommended_first_operation=None,
        clarification=ambiguous_clarification,
    )
