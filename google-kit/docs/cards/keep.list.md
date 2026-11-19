# keep.list

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/keep.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `page_size` | integer | No | Page Size (default: 50) |
| `filter` | string | No | Filter (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `notes` | array | Notes |

## Performance / Quota

- api: Keep v1
- method: notes.list
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit keep list`

**MCP tool:** `keep_list`
```json
{
  "page_size": 50
}
```

