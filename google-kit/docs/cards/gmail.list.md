# gmail.list

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | string | No | Gmail search query filter (default: None) |
| `label_ids` | array | No | Label IDs to filter by (default: None) |
| `max_results` | integer | No | Max Results (default: 25) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `messages` | array | Messages |

## Performance / Quota

- api: Gmail v1
- method: users.messages.list
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail list --label-ids '["INBOX"]' --max-results 10`

**MCP tool:** `gmail_list`
```json
{
  "label_ids": [
    "INBOX"
  ],
  "max_results": 10
}
```

