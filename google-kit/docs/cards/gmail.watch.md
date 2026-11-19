# gmail.watch

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic_name` | string | Yes | Fully-qualified Cloud Pub/Sub topic name (e.g. projects/my-project/topics/gmail-watch) |
| `label_ids` | array | No | Label IDs to watch (omit to watch all labels) (default: None) |
| `label_filter_behavior` | string | No | Label filter behavior: include or exclude (omit for default) (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `history_id` | string | Current history ID at the time the watch was started |
| `expiration` | string | Watch expiration timestamp (Unix ms string) |

## Performance / Quota

- api: Gmail v1
- method: users.watch
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail watch --topic-name projects/my-project/topics/gmail-watch --label-ids '["INBOX"]'`

**MCP tool:** `gmail_watch`
```json
{
  "topic_name": "projects/my-project/topics/gmail-watch",
  "label_ids": [
    "INBOX"
  ]
}
```
> **Note:** Requires an operator-provisioned Cloud Pub/Sub topic with Gmail service account publish access.

