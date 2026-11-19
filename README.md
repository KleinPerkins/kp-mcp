# kp-mcp

KleinPerkins MCP utility-kit monorepo: shared bootstrap/test engines and Google Workspace, Snowflake and widget kits. Runtime package names and versions are preserved.

Run `uv sync --locked`, then `.venv/bin/python -I -B scripts/verify.py local`. Six closed CI shards cover bootstrap, Google, Snowflake, widget, workspace and account/App delivery. CI is source preparation until qualified on the successor identity.

Each kit owns its install/bootstrap lifecycle; see its `docs/QUICKSTART.md`. Existing consumer commits/tags remain bound to the retained private original until a separate reviewed migration. Historical discovery/migration evidence is excluded; see [source boundary](docs/source-successor.md) and [CI delivery](docs/ci-delivery.md).
