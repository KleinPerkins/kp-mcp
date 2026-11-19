# people.connections

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/contacts.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `person_fields` | string | No | Comma-separated fields to return (default: 'names,emailAddresses') |
| `page_size` | integer | No | Page Size (default: 10) |
| `page_token` | string | No | Page token for continuation (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `connections` | array | Connections |

## Performance / Quota

- api: People v1
- method: people.connections.list
- quota: 90 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit people connections --page-size 10`

**MCP tool:** `people_connections`
```json
{
  "person_fields": "names,emailAddresses",
  "page_size": 10
}
```

