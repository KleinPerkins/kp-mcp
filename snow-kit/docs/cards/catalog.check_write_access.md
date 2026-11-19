# catalog.check_write_access

**Posture:** read  **Scopes:** `snowflake:read`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `object_name` | string | Yes | Object Name |
| `operation` | string | No | Write operation to check, e.g. INSERT or CREATE TABLE. (default: 'INSERT') |
| `role` | string | No | Role to use for spec explanation filtering. (default: None) |
| `email` | string | No | Optional email for spec role exploration. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `object_name` | string | Object Name |
| `operation` | string | Operation |
| `required_privilege` | string | Required Privilege |
| `active_role` | string | Active Role |
| `has_snowflake_grant` | boolean | Has Snowflake Grant |
| `matching_grants` | array | Matching Grants |
| `live_grants_decisive` | boolean | Live Grants Decisive |
| `spec_available` | boolean | Spec Available |
| `spec_revision` | string | Spec Revision |
| `spec_matches` | array | Spec Matches |
| `roles_for_email` | array | Roles For Email |

## Performance / Quota

- api: Snowflake
- method: SHOW GRANTS

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

**CLI:** `snow-kit catalog check_write_access --object-name EXAMPLE_DB.SCRATCH.MY_TABLE --operation INSERT`

**MCP tool:** `catalog_check_write_access`
```json
{
  "object_name": "EXAMPLE_DB.SCRATCH.MY_TABLE",
  "operation": "INSERT"
}
```

