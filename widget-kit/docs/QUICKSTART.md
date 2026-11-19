# widget-kit — Quickstart

Single-core / dual-surface Widget toolkit (CLI + MCP), scaffolded from
the kp-mcp kit template.

## Install (in the kp-mcp workspace)

```bash
uv sync                       # picks up widget-kit as a workspace member
uv run widget-kit --list    # list registered ops
```

## Run an op

```bash
uv run widget-kit items list --limit 5
uv run widget-kit items create --name demo
```

(The sample `items` service ships an in-memory test backend; wire your real
domain backend in `src/widget_kit/core/client.py` and the service `core.py`.)

## Auth

```bash
uv run widget-kit auth status
uv run widget-kit auth login     # wire your domain's credential flow first
```

## Registration authority

The Python registration API requires explicit context, prepared bytes and exact
approval. Only disposable fixtures qualify for writes in bootstrap 0.3.0;
ordinary CLI registration refuses before changing platform config. There is no
CLI flag that grants fixture authority to a live path. Existing entries require
ownership receipts or approved adoption. Registered config does not establish
enablement, authentication, discovery or successful service reads.

## Regenerate docs + schemas (deterministic; CI-gated)

```bash
uv run python -m widget_kit.schema_gen
uv run python -m widget_kit.docgen_gen
```

See `docs/dev/MCP-UTILITY-TEMPLATE.md` (in the workspace root) for the full
authoring recipe, and `docs/dev/SERVICE-PATTERN.md` to add a service.
