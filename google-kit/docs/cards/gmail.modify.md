# gmail.modify

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/gmail.modify`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | string | Yes | Gmail message ID to modify |
| `add_label_ids` | array | No | Label IDs to add |
| `remove_label_ids` | array | No | Label IDs to remove |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | string | Modified message ID |
| `label_ids` | array | Label IDs on the message after modification |

## Performance / Quota

- api: Gmail v1
- method: users.messages.modify
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail modify --message-id <msg-id> --remove-label-ids '["UNREAD"]'`

**MCP tool:** `gmail_modify`
```json
{
  "message_id": "<msg-id>",
  "remove_label_ids": [
    "UNREAD"
  ]
}
```

