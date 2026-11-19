# gmail.get

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | string | Yes | Gmail message ID |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `thread_id` | string | Thread Id |
| `snippet` | string | Snippet |
| `subject` | string | Subject |
| `from_` | string | From |
| `date` | string | Date |
| `body` | string | Body |
| `label_ids` | array | Label Ids |

## Performance / Quota

- api: Gmail v1
- method: users.messages.get
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail get --message-id <message-id>`

**MCP tool:** `gmail_get`
```json
{
  "message_id": "<message-id>"
}
```
> **Note:** Takes a message ID (from gmail.list or gmail.search data.messages[].id). thread_id is also returned in the response. Body is truncated at 500 characters to match legacy behavior (BD-8).

