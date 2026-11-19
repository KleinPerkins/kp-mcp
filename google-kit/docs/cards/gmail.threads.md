# gmail.threads

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | string | No | Gmail search query filter (e.g. 'from:boss@example.com') (default: None) |
| `label_ids` | array | No | Label IDs to filter threads by (default: None) |
| `max_results` | integer | No | Maximum number of threads to return (default: 25) |
| `page_token` | string | No | Page token for continuation (from a prior page.next_page_token) (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Number of threads returned on this page |
| `threads` | array | Thread references (id + snippet + history_id) |

## Performance / Quota

- api: Gmail v1
- method: users.threads.list
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail threads --label-ids '["INBOX"]' --max-results 10`

**MCP tool:** `gmail_threads`
```json
{
  "label_ids": [
    "INBOX"
  ],
  "max_results": 10
}
```

