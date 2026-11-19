# kp-mcp kit template

A real, runnable skeleton for a new `<domain>-kit` in the kp-mcp workspace. Files
are token-based (`*.tmpl`); the generator at `tools/new_kit.py` renders them into a
working kit that passes the parametrized CI.

## Scaffold a kit

```bash
uv run python tools/new_kit.py --domain widget
uv sync
uv run pytest widget-kit/
```

This creates `widget-kit/` (package `widget_kit`) with a sample `items` service,
both surfaces (CLI + MCP), deterministic generators, explicit-context registrar wiring, a
safety-rule stub, and passing tests. The workspace auto-discovers it (members glob
`["kp-mcp-*", "*-kit"]`) and CI picks it up with no YAML edits.

## What you get

| Path | Purpose |
|------|---------|
| `pyproject.toml` | versioned sibling deps + workspace sources + hatch build |
| `src/<pkg>/registry.py` | OpSpec + register + all_specs (single source of truth) |
| `src/<pkg>/core/` | output envelope + the `execute` API choke-point |
| `src/<pkg>/services/items/` | sample service: models + typed core fns + registration |
| `src/<pkg>/cli/` | generic CLI dispatcher + auth subcommands |
| `src/<pkg>/mcp/` | generic MCP stdio server over the registry |
| `src/<pkg>/bootstrap.py` | Cursor / Codex / Claude registrar wiring |
| `src/<pkg>/schema_gen.py`, `docgen_gen.py` | deterministic schema + card generators |
| `tests/` | registry, core-op, and registrar tests |
| `rules/<kit>-mcp-safety.mdc` | MCP safety-rule stub |
| `docs/QUICKSTART.md` | install + run + auth + bootstrap |

## Registrar compatibility

Generated kits exact-pin `kp-mcp-bootstrap==0.3.0`. Registration requires a
kit-owned stable identity, context, prepared operation and exact approval.
The CLI refuses live writes; fixture qualification is only available to isolated
test roots. Do not add an implicit approval callback or a fixture CLI switch.

## Tokens

The generator substitutes these in both file paths and file contents:

| Token | Meaning | Example |
|-------|---------|---------|
| `__KIT_NAME__` | kit / CLI / MCP-server name (hyphens) | `widget-kit` |
| `__PKG__` | Python package (underscores) | `widget_kit` |
| `__DOMAIN_TITLE__` | Title-cased domain | `Widget` |
| `__DOMAIN__` | domain slug | `widget` |

## Next steps after scaffolding

1. Replace the `items` sample with your real service(s) — see `docs/dev/SERVICE-PATTERN.md`.
2. Wire real auth + backends in `core/client.py` and `cli/auth.py`.
3. Regenerate docs + schemas, then refresh the catalog: `uv run python tools/catalog_gen.py`.

Full authoring recipe: `docs/dev/MCP-UTILITY-TEMPLATE.md`.
