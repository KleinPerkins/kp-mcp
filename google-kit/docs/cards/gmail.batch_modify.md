# gmail.batch_modify

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/gmail.modify`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ids` | array | Yes | Message IDs to modify (must be non-empty) |
| `add_label_ids` | array | No | Label IDs to add to every message |
| `remove_label_ids` | array | No | Label IDs to remove from every message |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `modified_count` | integer | Number of message IDs the label change was applied to |
| `ids` | array | Message IDs that were modified |
| `add_label_ids` | array | Label IDs added to every message |
| `remove_label_ids` | array | Label IDs removed from every message |

## Performance / Quota

- api: Gmail v1
- method: users.messages.batchModify
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail batch-modify --ids '["<msg-id-1>","<msg-id-2>"]' --remove-label-ids '["UNREAD"]'`

**MCP tool:** `gmail_batch_modify`
```json
{
  "ids": [
    "<msg-id-1>",
    "<msg-id-2>"
  ],
  "remove_label_ids": [
    "UNREAD"
  ]
}
```
> **Note:** Applies the same label change to every message ID in one request. The API returns HTTP 204 (empty body); the envelope reports modified_count and the ids/labels acted on.

