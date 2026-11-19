"""Generate per-op doc cards and docs/INDEX.md for widget-kit (deterministic).

Run::

    uv run python -m widget_kit.docgen_gen

Writes ``docs/cards/<name>.md`` (one per op) and ``docs/INDEX.md`` (intent →
card resolver). Re-running yields no diff; the CI determinism gate enforces this.
"""
from __future__ import annotations

import sys
from pathlib import Path

import widget_kit  # noqa: F401 — triggers service auto-registration
from widget_kit.registry import all_specs
from kp_mcp_bootstrap.docgen import Docgen


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

    index = (
        "# widget-kit capabilities index\n\n"
        "Intent → capability card resolver.\n\n"
        "| Operation | Posture | Card |\n"
        "|-----------|---------|------|\n"
        + "\n".join(rows)
        + "\n"
    )
    out_index.write_text(index, encoding="utf-8")
    print(f"Generated {len(specs)} cards in {out_cards}", file=sys.stderr)


if __name__ == "__main__":
    generate()
