# gmail.send

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/gmail.compose`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `to` | string | Yes | Recipient email address |
| `subject` | string | Yes | Email subject line |
| `body_text` | string | Yes | Plain-text email body |
| `cc` | string | No | CC recipient email address (optional) (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | string | Sent message ID |
| `thread_id` | string | Thread ID the message was placed in |
| `label_ids` | array | Label IDs applied to the sent message |

## Performance / Quota

- api: Gmail v1
- method: users.messages.send
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail send --to bob@example.com --subject Meeting --body-text 'See you at 3pm.'`

**MCP tool:** `gmail_send`
```json
{
  "to": "bob@example.com",
  "subject": "Meeting",
  "body_text": "See you at 3pm."
}
```

