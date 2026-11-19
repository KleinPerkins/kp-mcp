"""Generate the intent/alias/keyword manifest (docs/INTENTS.md) from the registry.

Run::

    uv run python -m google_kit.aliases_gen

The manifest is the human/agent-reviewable surface behind ``google-kit help
<intent>`` and the MCP ``help`` tool (E6). It is regenerated like the schema and
doc cards (deterministic; CI determinism-gated) so it never drifts from the
registry. Curated intent phrases live in ``core/manifest._CURATED_ALIASES`` (and
on ``OpSpec.aliases``); service synonyms in ``_SERVICE_TRIGGERS``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import google_kit  # noqa: F401 — triggers service auto-registration
from google_kit.core.manifest import curated_aliases, op_triggers
from google_kit.registry import all_specs


def _manifest_path() -> Path:
    return Path(__file__).parent.parent.parent / "docs" / "INTENTS.md"


def _cli_form(op: str) -> str:
    svc, _, rest = op.partition(".")
    return f"{svc} {rest.replace('_', '-')}"


def generate(*, manifest_path: Path | None = None) -> None:
    """Write docs/INTENTS.md for all registered ops (deterministic)."""
    out = manifest_path or _manifest_path()
    specs = sorted(all_specs(), key=lambda s: s.name)

    curated_rows: list[str] = []
    for s in specs:
        for phrase in curated_aliases(s.name):
            curated_rows.append(f"| {phrase} | `{s.name}` | `google-kit {_cli_form(s.name)}` |")
    curated_rows.sort()

    trigger_rows = [
        f"| `{s.name}` | `google-kit {_cli_form(s.name)}` | {getattr(s, 'plane', None) or '—'} "
        f"| {', '.join(sorted(op_triggers(s)))} |"
        for s in specs
    ]

    doc = (
        "# google-kit intent manifest\n\n"
        "Natural-language → operation triggers behind `google-kit help <intent>` and the\n"
        "MCP `help` tool. Generated from the registry — do not edit by hand; run\n"
        "`uv run python -m google_kit.aliases_gen`. Curate phrases in\n"
        "`core/manifest._CURATED_ALIASES` / `OpSpec.aliases`; service synonyms in\n"
        "`_SERVICE_TRIGGERS`.\n\n"
        "## Common intents (curated)\n\n"
        "Hand-curated phrases for the workhorse operations — the operator-signed\n"
        "discovery surface. Every other op stays discoverable via its name tokens and\n"
        "service synonyms (see the trigger table below).\n\n"
        "| Intent | Operation | CLI |\n"
        "|--------|-----------|-----|\n"
        + "\n".join(curated_rows)
        + "\n\n"
        "## Operation triggers\n\n"
        "All match tokens per op (name + capability + curated/explicit aliases [strong] "
        "and service synonyms [weak]). The resolver ranks strong-token and exact-phrase "
        "hits above shared service synonyms.\n\n"
        "| Operation | CLI | Plane | Triggers |\n"
        "|-----------|-----|-------|----------|\n"
        + "\n".join(trigger_rows)
        + "\n"
    )

    out.write_text(doc, encoding="utf-8")
    print(f"Generated {out} ({len(specs)} ops, {len(curated_rows)} curated intents)", file=sys.stderr)


if __name__ == "__main__":
    generate()
