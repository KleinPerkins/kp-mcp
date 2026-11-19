# catalog.preview_table

**Posture:** read  **Scopes:** `snowflake:read`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `table_name` | string | Yes | Table Name |
| `limit` | integer | No | Limit (default: 10) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `rows` | array | Rows |
| `count` | integer | Count |
| `truncated` | boolean | Truncated |
| `execution_time_ms` | number | Execution Time Ms |

## Performance / Quota

- api: Snowflake
- method: SELECT LIMIT

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

**CLI:** `snow-kit catalog preview_table --table-name EXAMPLE_DB.PUBLIC.MY_TABLE --limit 10`

**MCP tool:** `catalog_preview_table`
```json
{
  "table_name": "EXAMPLE_DB.PUBLIC.MY_TABLE",
  "limit": 10
}
```

