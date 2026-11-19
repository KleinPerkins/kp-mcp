"""Generate per-op doc cards and docs/INDEX.md for snow-kit (deterministic).

Run::

    uv run python -m snow_kit.docgen_gen

Writes ``docs/cards/<name>.md`` (one per op) and ``docs/INDEX.md`` (intent →
card resolver). Re-running yields no diff; the CI determinism gate enforces this.
"""
from __future__ import annotations

import sys
from pathlib import Path

import snow_kit  # noqa: F401 — triggers service auto-registration
from kp_mcp_bootstrap.docgen import Docgen
from snow_kit.mcp.metadata import HELP_TOOL_DESCRIPTION
from snow_kit.registry import all_specs


def _cards_dir() -> Path:
    return Path(__file__).parent.parent.parent / "docs" / "cards"


def _index_path() -> Path:
    return Path(__file__).parent.parent.parent / "docs" / "INDEX.md"


def generate(*, cards_dir: Path | None = None, index_path: Path | None = None) -> None:
    """Write doc cards and INDEX.md for all registered ops."""
    docgen = Docgen()
    out_cards = cards_dir or _cards_dir()
    out_index = index_path or _index_path()
    out_cards.mkdir(parents=True, exist_ok=True)

    specs = sorted(all_specs(), key=lambda s: s.name)
    rows: list[str] = []
    for spec in specs:
        (out_cards / f"{spec.name}.md").write_text(docgen.emit_markdown(spec), encoding="utf-8")
        rows.append(f"| `{spec.name}` | {spec.posture} | [card](cards/{spec.name}.md) |")
    (out_cards / "help.md").write_text(_help_card(), encoding="utf-8")
    rows.insert(0, "| `help` | read | [card](cards/help.md) |")

    index = (
        "# snow-kit capabilities index\n\n"
        "Intent → capability card resolver. For plain-English routing cues and "
        "conditional workflows, see [INTENTS.md](INTENTS.md).\n\n"
        "| Operation | Posture | Card |\n"
        "|-----------|---------|------|\n"
        + "\n".join(rows)
        + "\n"
    )
    out_index.write_text(index, encoding="utf-8")
    print(f"Generated {len(specs) + 1} cards in {out_cards}", file=sys.stderr)


def _help_card() -> str:
    return (
        "# help\n\n"
        "**Posture:** read  **MCP annotations:** read-only, non-destructive, "
        "idempotent, closed-world\n\n"
        f"{HELP_TOOL_DESCRIPTION}\n\n"
        "## Input\n\n"
        "| Field | Type | Required | Description |\n"
        "|-------|------|----------|-------------|\n"
        "| `intent` | string | Yes | Complete plain-English task to route. |\n"
        "| `limit` | integer | No | Maximum matches, 1 through 10 (default 5). |\n\n"
        "## Output\n\n"
        "Ranked operation matches, weighted cue reasons, required arguments, "
        "safety posture, conditional next actions, and configured workflow "
        "recommendations. `ambiguous` results never include an executable next "
        "action. `no_match` results request clarification.\n\n"
        "## Safety\n\n"
        "Help reads registry metadata only. It performs no Snowflake query, "
        "context retrieval, filesystem read, or write. Existing context, SQL, "
        "catalog, permission, and row-limit gates remain authoritative.\n"
    )


if __name__ == "__main__":
    generate()
