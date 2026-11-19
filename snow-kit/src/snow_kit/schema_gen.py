"""Generate MCP tool schemas for all registered snow-kit ops (deterministic).

Run::

    uv run python -m snow_kit.schema_gen

Writes one ``docs/schemas/<name>.json`` per op plus a combined ``_manifest.json``.
Re-running yields no diff — the CI determinism gate double-runs this and asserts
a clean ``git diff``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import snow_kit  # noqa: F401 — triggers service auto-registration
from kp_mcp_bootstrap.docgen import Docgen
from snow_kit.core.intents import HelpInput, HelpOutput
from snow_kit.mcp.metadata import HELP_TOOL_DESCRIPTION, tool_description
from snow_kit.registry import all_specs


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
        schema["description"] = tool_description(spec)
        json_text = json.dumps(schema, sort_keys=True, indent=2) + "\n"
        (out / f"{spec.name}.json").write_text(json_text, encoding="utf-8")
        manifest[spec.name] = f"{spec.name}.json"

    help_schema = {
        "name": "help",
        "description": HELP_TOOL_DESCRIPTION,
        "inputSchema": HelpInput.model_json_schema(),
        "outputSchema": HelpOutput.model_json_schema(),
    }
    (out / "help.json").write_text(
        json.dumps(help_schema, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest_text = (
        json.dumps(
            {
                "meta_tools": {"help": "help.json"},
                "ops": manifest,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    (out / "_manifest.json").write_text(manifest_text, encoding="utf-8")
    print(f"Generated {len(specs)} MCP schemas in {out}", file=sys.stderr)


if __name__ == "__main__":
    generate()
