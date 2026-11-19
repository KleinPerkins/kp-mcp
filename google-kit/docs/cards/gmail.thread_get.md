# gmail.thread_get

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `thread_id` | string | Yes | Gmail thread ID |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Thread ID |
| `history_id` | string | History ID of the thread |
| `snippet` | string | Snippet of the thread's latest message |
| `message_count` | integer | Number of messages in the thread |
| `messages` | array | Messages in the thread, oldest first |

## Performance / Quota

- api: Gmail v1
- method: users.threads.get
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail thread-get --thread-id <thread-id>`

**MCP tool:** `gmail_thread_get`
```json
{
  "thread_id": "<thread-id>"
}
```
> **Note:** Takes a thread ID (from gmail.threads data.threads[].id or gmail.get data.thread_id). Returns messages[] with decoded bodies truncated at 500 chars (BD-8).

