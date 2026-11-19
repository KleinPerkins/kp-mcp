# query.execute_write

**Posture:** write  **Scopes:** `snowflake:write`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | Yes | Single write SQL statement gated by SNOW_KIT_ENABLE_WRITE=1. |
| `confirm_write` | boolean | No | Must be true for write execution. (default: False) |
| `justification` | string | No | Human-readable reason for audit context. |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `operation` | string | Operation |
| `targets` | array | Targets |
| `affected_rows` | integer | Affected Rows |
| `execution_time_ms` | number | Execution Time Ms |

## Performance / Quota

- api: Snowflake
- requires: SNOW_KIT_ENABLE_WRITE=1

## Errors

| Class | When | Retry |
|-------|------|-------|
| `Auth` | Snowflake SSO or cached authentication is unavailable | Run snow-kit auth login; do not retry unchanged |
| `Permission` | Live grants or a server-side safety policy denies the request | Do not retry unchanged |
| `Validation` | Arguments, SQL, context references, or configuration are invalid | Correct the input, then retry once |
| `Unavailable` | An approved local context source cannot be read safely | Repair setup or source state; never treat as no matches |
| `Timeout` | A tool, query, or local lock exceeds its configured limit | Narrow the request; no automatic retry |
| `Transient` | The Snowflake connection fails transiently | Retry once only when the operation is idempotent |
| `Unknown` | The failure cannot be classified safely | Escalate; do not retry automatically |
## Example

**CLI:** `SNOW_KIT_ENABLE_WRITE=1 snow-kit query execute_write --query 'INSERT ...' --confirm-write --justification 'scratch smoke'`

**MCP tool:** `query_execute_write`
```json
{
  "query": "INSERT INTO SCRATCH.DEMO VALUES (1)",
  "confirm_write": true,
  "justification": "scratch smoke"
}
```

