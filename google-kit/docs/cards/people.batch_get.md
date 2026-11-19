# people.batch_get

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/directory.readonly` `https://www.googleapis.com/auth/contacts.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `resource_names` | array | Yes | Resource names to fetch |
| `person_fields` | string | No | Comma-separated fields to return (default: 'names,emailAddresses') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `people` | array | People |

## Performance / Quota

- api: People v1
- method: people.getBatchGet
- quota: 90 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit people batch-get --resource-names '["people/p001","people/p002"]'`

**MCP tool:** `people_batch_get`
```json
{
  "resource_names": [
    "people/p001",
    "people/p002"
  ],
  "person_fields": "names,emailAddresses"
}
```

