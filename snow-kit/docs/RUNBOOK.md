# snow-kit operator runbook

## Scope

`snow-kit` provides a generic Snowflake CLI and a fail-closed read-only MCP.
Operator connection values remain in the private canonical profile.

## Offline validation

```bash
uv sync
uv run pytest snow-kit/ -q
uv run python -m snow_kit.schema_gen
uv run python -m snow_kit.docgen_gen
uv run python tools/catalog_gen.py
uv run python -m kp_mcp_testkit.editorial snow-kit
uv run snow-kit doctor --skip-registrations
```

## Live read smoke

Run only when browser SSO and Snowflake access are available:

```bash
uv run snow-kit auth login
uv run snow-kit query execute --query "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_SCHEMA()"
uv run snow-kit catalog list_tables --database EXAMPLE_DB --schema PUBLIC --limit 5
uv run snow-kit catalog preview_table --table-name EXAMPLE_DB.PUBLIC.<KNOWN_TABLE> --limit 5
uv run snow-kit query analyze --query "SELECT * FROM EXAMPLE_DB.PUBLIC.<KNOWN_TABLE> LIMIT 5"
```

Do not use sensitive tables for smoke validation.

## Cutover

Blocked for source 0.3.0 until a native writer mechanism and the exact owner
migration are separately qualified and authorized. `snow-kit bootstrap` has no
CLI authority envelope and cannot complete registration. Do not run the sequence
below as an implementation smoke test.

1. Stage the candidate without changing clients: `snow-kit/install.sh --stage-only`.
2. Run `snow-kit doctor --skip-registrations`.
3. Run `snow-kit auth login`, then `snow-kit doctor --live --skip-registrations`.
4. Use the qualified owner workflow to preview, prepare and approve the exact
   registration and any legacy-writer handoff. No duplicate app-managed entry.
5. Confirm `query_execute`, `query_analyze`, and catalog tools behave
   semantically like legacy tools.
6. Remove the legacy server only after the live checks pass.

## Rollback

Binary restoration is separate from registrar rollback. Registrar rollback
requires an exact committed-receipt or pending-journal reference, a new prepared
inverse and approval, matching current config/ownership bytes and qualified
writer exclusion. Recovery material stays private; later user edits block exact
restoration. Live rollback remains unavailable while native exclusion is
unqualified. No profile or authentication-cache mutation is implied.

## Shared multi-chat MCP concurrency

The snow-kit MCP stdio server is safe for multiple concurrent Cursor chats against
one process:

- Tool handlers offload blocking Snowflake I/O with `asyncio.to_thread` so one
  slow query does not starve the shared event loop.
- The process-wide `SnowflakeSession` serializes connector/cursor use behind an
  `RLock`, so concurrent tool calls cannot interleave cursor state or leave stale
  transactions.
- The initial `externalbrowser` connect/auth path also takes a host-local
  `fcntl.flock` lock, matching google-kit's ADR B21 pattern for cross-process
  auth serialization. Ordinary queries do not take this file lock after a
  session is connected.
- The Snowflake connector is installed with the `secure-local-storage` extra so
  its local secure token cache/keyring support is available for repeated SSO
  authentication on hosts with a working keyring.
- Registered MCP invocations always use `mcp --read-only`; inherited write
  settings cannot expose or invoke mutation tools.

Residual limits:

- Concurrent chats share one Snowflake connection and execute queries one at a
  time. A long-running query blocks later calls until it finishes or hits the
  configured statement/tool timeout.
- Browser SSO (`externalbrowser`) is process-wide; the first chat that needs SSO
  may block others until login completes. Prefer `snow-kit auth login` in a
  terminal before shared MCP cutover. Keep the username in the private
  canonical profile; client registrations contain only its path.
- The SSO lock is per host and per local filesystem only; it cannot coordinate
  separate machines or containers that do not share the same lock path.
- Two separate MCP server processes still have independent Snowflake sessions
  after auth completes; the file lock only prevents repeated concurrent browser
  auth during initial connect.
