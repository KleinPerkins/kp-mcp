# snow-kit — Quickstart

Independent Snowflake CLI and fail-closed read-only MCP.

## Install (in the kp-mcp workspace)

```bash
uv sync                       # picks up snow-kit as a workspace member
uv run snow-kit --list        # list registered ops
```

## Configure

The 0.3.0 registration API requires owner context, prepared bytes and exact
operation approval. Only disposable fixtures qualify for config/state writes;
live registration is blocked until native writer exclusion is qualified.
`setup` and `repair` refuse before profile writes when that authority is missing.
The CLI does not create an approval or grant fixture authority to a supplied path.

The existing secure dotenv profile remains at
`${XDG_CONFIG_HOME:-~/.config}/snow-kit/config.env`.
`SNOW_KIT_CONFIG_PATH` can point to another absolute profile. This registrar
release does not change profile or authentication implementations.

When the checkout contains the tracked governance markers
`business-context/README.md` and
`business-context/governance/governance.md`, setup approves only
`business-context/**/*.md`. Otherwise, pass one or more exact Markdown allow
patterns with `--context-path`; setup never approves the whole repository.
Use `--context-mode strict` to reject table-bearing analytical SQL without a
validated context reference. The default is warning-only.

Runtime precedence remains process `SNOW_KIT_*`, then the profile, then neutral
defaults. Legacy `SNOWFLAKE_*` connection aliases and unversioned v0.1 profiles
remain readable in this registrar-focused 0.3.0 source version; removing them
requires a separate profile migration. Unknown keys,
symlinks, unsafe ownership/permissions, relative context roots, and unsafe
allow paths fail closed.

## Browser SSO

```bash
uv run snow-kit auth status
uv run snow-kit auth login
```

Run `auth login` before first MCP use. Snowflake's `externalbrowser` flow can
take longer than MCP stdio timeouts; the CLI path lets the browser handshake
complete outside the agent transport. The package depends on
`snowflake-connector-python[secure-local-storage]`, so the Snowflake connector
can use its local secure token cache/keyring support for repeated SSO logins
when the host keyring is available.

Only the initial `externalbrowser` connect path is serialized across snow-kit
processes on the same host. The lock is an empty local file under
`${SNOW_KIT_AUTH_LOCK_DIR}` when set, else `${SNOW_KIT_STATE_DIR}/locks`, else
`${XDG_STATE_HOME:-~/.local/state}/snow-kit/locks`; the directory is created
operator-local and the lock file contains no secrets. If another process holds
the SSO lock longer than `SNOW_KIT_AUTH_LOCK_TIMEOUT` seconds (default `60`),
snow-kit returns a structured timeout instead of launching another browser auth.

## Read tools

```bash
uv run snow-kit query execute --query "SELECT 1"
uv run snow-kit query analyze --query "SELECT * FROM EXAMPLE_DB.PUBLIC.MY_TABLE"
uv run snow-kit catalog list_tables --database EXAMPLE_DB --schema PUBLIC
uv run snow-kit catalog describe_table --table-name EXAMPLE_DB.PUBLIC.MY_TABLE
uv run snow-kit catalog preview_table --table-name EXAMPLE_DB.PUBLIC.MY_TABLE --limit 10
uv run snow-kit catalog search_columns --column-name USER%
uv run snow-kit catalog get_table_stats --table-name EXAMPLE_DB.PUBLIC.MY_TABLE
uv run snow-kit catalog check_write_access --object-name EXAMPLE_DB.SCRATCH.DEMO --operation INSERT
```

## Plain-English help

```bash
uv run snow-kit help search analytics context
uv run snow-kit help "find the GMV column"
```

The CLI and MCP `help` tool deterministically rank visible operations and
configured workflows from registry metadata. Help performs no Snowflake query,
context retrieval, or write. For ambiguous or multi-step analytics requests,
call `help` with the complete request before selecting an operation. The
server-side ranking is deterministic; whether Cursor or another model initially
selects `help` remains model-dependent.

Composite metric/segment/time-window requests recommend a conditional,
context-first workflow: search context, read a relevant bounded section,
clarify definitions, inspect only known catalog scope, optionally analyze SQL,
then execute validated bounded `SELECT`/`WITH`. A valid context reference proves
approved provenance, not semantic relevance. If context or scope is missing,
stop and clarify; do not replace it with broad `INFORMATION_SCHEMA` discovery.
`max_rows` limits returned rows, not warehouse scanning. Snow-kit returns rows
and does not render charts.

See [INTENTS.md](INTENTS.md) for the generated routing manifest.

## Authoritative analytics context

```bash
uv run snow-kit context search --query "Example Shop return rate" --limit 5
uv run snow-kit context get \
  --document-id <document_id> \
  --revision <revision> \
  --section "Data Sources & Joins"
uv run snow-kit query execute \
  --query "SELECT ..." \
  --context-refs '[{"document_id":"<document_id>","revision":"<revision>"}]'
```

Each call pins one local commit and reads only Git-tracked approved Markdown
blobs from that commit. It does not fetch. Symlinks, submodules, LFS pointers,
sandbox/archive/instruction/data paths, invalid UTF-8, oversized content, and
working-tree content are not served. Results contain bounded redacted snippets
or sections, opaque document IDs, the exact revision, relative provenance,
freshness/conflict warnings, and truncation state. A source failure is reported
as unavailable, never as zero matches.

## Lifecycle

```bash
uv run snow-kit setup
uv run snow-kit status
uv run snow-kit doctor
```

`bootstrap` is registration-only. All registration callers require explicit
context; mutations additionally require prepared bytes and exact approval.
Status uses owned-projection inspection, preserves host policy and never exposes
raw entries. A write-enabling override produces `policy_conflict` even when
`mcp --read-only` is present. Missing authority is reported as a bounded refusal,
not a successful repair. Runtime enablement/authentication/discovery/read states
remain unknown from registration alone.

## Cutover and rollback

Phase D read cutover remains separately authorized. The historical sequence
below requires qualified native registration before its setup step; source
0.3.0 cannot complete that step while live writes remain blocked:

1. Run `uv run snow-kit doctor --skip-registrations` on the staged binary.
2. Run `uv run snow-kit auth login`.
3. Run `uv run snow-kit doctor --live --skip-registrations`.
4. Run `uv run snow-kit setup`, then `uv run snow-kit doctor`.
5. Remove the legacy server only after the live doctor succeeds.

Rollback: restore the previous binary and its backed-up client registrations.

## Regenerate docs + schemas (deterministic; CI-gated)

```bash
uv run python -m snow_kit.schema_gen
uv run python -m snow_kit.docgen_gen
uv run python -m snow_kit.aliases_gen
uv run python tools/catalog_gen.py
uv run python -m kp_mcp_testkit.editorial snow-kit
```
