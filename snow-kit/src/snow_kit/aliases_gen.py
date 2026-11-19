"""Generate snow-kit's deterministic intent and workflow manifest."""
from __future__ import annotations

import sys
from pathlib import Path

import snow_kit  # noqa: F401 — triggers service auto-registration
from snow_kit.core.intents import (
    curated_aliases,
    op_triggers,
    workflow_definitions,
)
from snow_kit.registry import all_specs


def _manifest_path() -> Path:
    return Path(__file__).parent.parent.parent / "docs" / "INTENTS.md"


def _cli_form(operation: str) -> str:
    service, _, name = operation.partition(".")
    return f"{service} {name}"


def generate(*, manifest_path: Path | None = None) -> None:
    """Write the operator-readable routing manifest from approved metadata."""
    output = manifest_path or _manifest_path()
    specs = sorted(all_specs(), key=lambda spec: spec.name)

    curated_rows = sorted(
        f"| {phrase} | `{spec.name}` | `snow-kit {_cli_form(spec.name)}` |"
        for spec in specs
        for phrase in curated_aliases(spec.name)
    )
    trigger_rows = [
        f"| `{spec.name}` | {spec.posture} | `snow-kit {_cli_form(spec.name)}` "
        f"| {', '.join(sorted(op_triggers(spec)))} |"
        for spec in specs
    ]

    workflow_sections: list[str] = []
    for workflow in workflow_definitions():
        cue_rows = [
            f"| {group.name} | {', '.join(group.cues)} | {group.weight:g} |"
            for group in workflow.cue_groups
        ]
        step_rows = [
            f"| {index} | {step.kind} | {step.tool or '—'} | {step.instruction} | "
            f"{'; '.join(step.prerequisites) or '—'} | "
            f"{'; '.join(step.stop_if) or '—'} |"
            for index, step in enumerate(workflow.steps, start=1)
        ]
        qualification = (
            f"Qualifies when at least {workflow.minimum_groups} cue groups match"
        )
        if workflow.required_groups:
            qualification += "; required groups: " + ", ".join(
                f"`{name}`" for name in workflow.required_groups
            )
        workflow_sections.append(
            f"### `{workflow.id}` — {workflow.title}\n\n"
            f"{workflow.summary}\n\n"
            f"{qualification}.\n\n"
            "| Cue group | Approved cues | Weight |\n"
            "|-----------|---------------|--------|\n"
            + "\n".join(cue_rows)
            + "\n\n"
            "| Step | Kind | Tool | Instruction | Preconditions | Stop if |\n"
            "|------|------|------|-------------|---------------|---------|\n"
            + "\n".join(step_rows)
            + "\n\n"
            "Limitations:\n"
            + "\n".join(f"- {item}" for item in workflow.limitations)
        )

    document = (
        "# snow-kit intent manifest\n\n"
        "Plain-English routing metadata behind `snow-kit help <intent>` and the "
        "MCP `help` tool. Generated from the registry and Snow-owned routing "
        "configuration; do not edit by hand. Run "
        "`uv run python -m snow_kit.aliases_gen`.\n\n"
        "Resolution is deterministic server-side. Cursor/model selection of the "
        "initial tool remains model-dependent. Help performs no Snowflake query, "
        "context retrieval, or write.\n\n"
        "## Common intents\n\n"
        "| Intent | Operation | CLI |\n"
        "|--------|-----------|-----|\n"
        + "\n".join(curated_rows)
        + "\n\n"
        "## Operation triggers\n\n"
        "Strong operation/curated/alias/keyword cues rank above weak service "
        "synonyms. Ambiguous requests return candidates and reasons without an "
        "executable recommendation.\n\n"
        "| Operation | Posture | CLI | Triggers |\n"
        "|-----------|---------|-----|----------|\n"
        + "\n".join(trigger_rows)
        + "\n\n"
        "## Configured workflows\n\n"
        + "\n\n".join(workflow_sections)
        + "\n\n"
        "## Safety boundaries\n\n"
        "- Workflows are conditional recommendations, not execution orchestration.\n"
        "- Valid context provenance does not prove semantic relevance.\n"
        "- Missing context never authorizes broad `INFORMATION_SCHEMA` discovery.\n"
        "- Existing context modes, SQL validation, permissions, and row caps remain authoritative.\n"
        "- `max_rows` caps returned rows, not warehouse scanning; `USE` changes session state.\n"
        "- Snow-kit returns rows and does not render charts.\n"
    )
    output.write_text(document, encoding="utf-8")
    print(
        f"Generated {output} ({len(specs)} ops, {len(curated_rows)} curated intents)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    generate()
