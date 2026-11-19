# gmail.history

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start_history_id` | string | Yes | History ID to start listing from (exclusive) |
| `history_types` | array | No | Event types to include: messageAdded, messageDeleted, labelAdded, labelRemoved (default: None) |
| `label_id` | string | No | Filter history by label ID (default: None) |
| `max_results` | integer | No | Max Results (default: 100) |
| `page_token` | string | No | Page token for continuation (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `history` | array | History |
| `history_id` | string | History Id |

## Performance / Quota

- api: Gmail v1
- method: users.history.list
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail history --start-history-id 12345 --history-types '["messageAdded"]'`

**MCP tool:** `gmail_history`
```json
{
  "start_history_id": "12345",
  "history_types": [
    "messageAdded"
  ],
  "max_results": 50
}
```

