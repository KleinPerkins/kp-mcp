"""Generate MCP tool schemas for all registered widget-kit ops (deterministic).

Run::

    uv run python -m widget_kit.schema_gen

Writes one ``docs/schemas/<name>.json`` per op plus a combined ``_manifest.json``.
Re-running yields no diff — the CI determinism gate double-runs this and asserts
a clean ``git diff``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import widget_kit  # noqa: F401 — triggers service auto-registration
from widget_kit.registry import all_specs
from kp_mcp_bootstrap.docgen import Docgen


def _schemas_dir() -> Path:
    return Path(__file__).parent.parent.parent / "docs" / "schemas"


def generate(*, schemas_dir: Path | None = None) -> None:
    """Write MCP tool schema JSON files for all registered ops."""
    docgen = Docgen()
    out = schemas_dir or _schemas_dir()
    out.mkdir(parents=True, exist_ok=True)

    specs = sorted(all_specs(), key=lambda s: s.name)
    manifest: dict[str, str] = {}
    for spec in specs:
        schema = docgen.emit_mcp_schema(spec)
        json_text = json.dumps(schema, sort_keys=True, indent=2) + "\n"
        (out / f"{spec.name}.json").write_text(json_text, encoding="utf-8")
        manifest[spec.name] = f"{spec.name}.json"

    manifest_text = json.dumps({"ops": manifest}, sort_keys=True, indent=2) + "\n"
    (out / "_manifest.json").write_text(manifest_text, encoding="utf-8")
    print(f"Generated {len(specs)} MCP schemas in {out}", file=sys.stderr)


if __name__ == "__main__":
    generate()
