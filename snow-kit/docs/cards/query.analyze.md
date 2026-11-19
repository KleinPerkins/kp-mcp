# query.analyze

**Posture:** read  **Scopes:** `snowflake:read`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | Yes | Read-only SQL query to EXPLAIN and analyze. |
| `context_refs` | array | No | Validated document_id/revision pairs returned by context.search. |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `execution_plan` | array | Execution Plan |
| `performance_issues` | array | Performance Issues |
| `recommendations` | array | Recommendations |
| `execution_time_ms` | number | Execution Time Ms |

## Performance / Quota

- api: Snowflake
- method: EXPLAIN

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

**CLI:** `snow-kit query analyze --query 'SELECT * FROM MY_TABLE'`

**MCP tool:** `query_analyze`
```json
{
  "query": "SELECT * FROM MY_TABLE"
}
```

