# help

**Posture:** read  **MCP annotations:** read-only, non-destructive, idempotent, closed-world

Call this first for an ambiguous or multi-step plain-English analytics request. Deterministically ranks visible snow-kit operations and conditional context-first workflows; performs no Snowflake query or context retrieval.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `intent` | string | Yes | Complete plain-English task to route. |
| `limit` | integer | No | Maximum matches, 1 through 10 (default 5). |

## Output

Ranked operation matches, weighted cue reasons, required arguments, safety posture, conditional next actions, and configured workflow recommendations. `ambiguous` results never include an executable next action. `no_match` results request clarification.

## Safety

Help reads registry metadata only. It performs no Snowflake query, context retrieval, filesystem read, or write. Existing context, SQL, catalog, permission, and row-limit gates remain authoritative.
