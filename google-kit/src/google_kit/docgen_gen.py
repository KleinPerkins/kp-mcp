"""Generate per-capability doc cards and docs/INDEX.md from the registry.

Run::

    uv run python -m google_kit.docgen_gen

Writes:
  google-kit/docs/cards/<name>.md   — one card per registered OpSpec
  google-kit/docs/INDEX.md          — intent → card resolver
"""
from __future__ import annotations

import sys
from pathlib import Path

import google_kit  # noqa: F401 — triggers service auto-registration
from google_kit.registry import all_specs
from kp_mcp_bootstrap.docgen import Docgen

# URL-routing behaviours: capabilities handled by existing ops, not a separate op card.
# Add new rows here when an op routes additional URL patterns.
_ROUTED_ALIASES = [
    (
        "Google Sites (`https://sites.google.com/…`)",
        "drive.fetch",
        "Pass the Sites URL as `url_or_id`. Requires Chrome + browser_cookie3 + Playwright — see [Google Sites prerequisites](QUICKSTART.md#google-sites-prerequisites).",
    ),
]


_NATIVE_HOST_NOTE = 'Native host connectors can consume canonical document style data through the\n[bounded native Doc style provider route](../../docs/runbooks/native-doc-style-provider.md).\nThis separate interface does not replace CLI/MCP registration or qualify the\nfull operation index.\n\n'


def _cards_dir() -> Path:
    here = Path(__file__).parent
    return here.parent.parent / "docs" / "cards"


def _index_path() -> Path:
    here = Path(__file__).parent
    return here.parent.parent / "docs" / "INDEX.md"


def generate(*, cards_dir: Path | None = None, index_path: Path | None = None) -> None:
    """Write doc cards and INDEX.md for all registered ops."""
    docgen = Docgen()
    out_cards = cards_dir or _cards_dir()
    out_index = index_path or _index_path()
    out_cards.mkdir(parents=True, exist_ok=True)

    specs = sorted(all_specs(), key=lambda s: s.name)
    index_rows: list[str] = []

    for spec in specs:
        md = docgen.emit_markdown(spec)
        card_file = out_cards / f"{spec.name}.md"
        card_file.write_text(md, encoding="utf-8")
        index_rows.append(f"| `{spec.name}` | {spec.posture} | [card](cards/{spec.name}.md) |")

    index = (
        "# google-kit capabilities index\n\n"
        "Intent → capability card resolver.\n\n"
        "> **Prerequisite:** authenticate before calling any op — see [QUICKSTART.md](QUICKSTART.md).\n"
        "> Error triage: [docs/dev/TRIAGE.md](../../docs/dev/TRIAGE.md).\n\n"
        "| Operation | Posture | Card |\n"
        "|-----------|---------|------|\n"
        + "\n".join(index_rows)
        + "\n"
    )

    if _ROUTED_ALIASES:
        routed_rows = [
            f"| {intent} | `{op}` | {note} |"
            for intent, op, note in _ROUTED_ALIASES
        ]
        index += (
            "\n## Routed capabilities\n\n"
            + _NATIVE_HOST_NOTE
            + "These are not separate ops — they are URL-routing behaviours within existing ops.\n\n"
            "| Intent | Handled by | Notes |\n"
            "|--------|------------|-------|\n"
            + "\n".join(routed_rows)
            + "\n"
        )

    out_index.write_text(index, encoding="utf-8")
    print(f"Generated {len(specs)} cards in {out_cards}", file=sys.stderr)
    print(f"Generated {out_index}", file=sys.stderr)


if __name__ == "__main__":
    generate()
