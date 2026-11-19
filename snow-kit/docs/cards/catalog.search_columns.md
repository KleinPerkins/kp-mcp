# catalog.search_columns

**Posture:** read  **Scopes:** `snowflake:read`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `column_name` | string | Yes | Column Name |
| `database` | string | No | Database (default: None) |
| `schema` | string | No | Schema (default: None) |
| `limit` | integer | No | Limit (default: 1000) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `rows` | array | Rows |
| `count` | integer | Count |
| `truncated` | boolean | Truncated |
| `execution_time_ms` | number | Execution Time Ms |

## Performance / Quota

- api: Snowflake
- method: SHOW COLUMNS

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

**CLI:** `snow-kit catalog search_columns --column-name USER%`

**MCP tool:** `catalog_search_columns`
```json
{
  "column_name": "USER%"
}
```

