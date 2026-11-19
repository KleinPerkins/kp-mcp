# gmail.draft

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
| `draft_id` | string | Gmail draft ID |
| `message_id` | string | Draft's inner message ID |

## Performance / Quota

- api: Gmail v1
- method: users.drafts.create
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail draft --to alice@example.com --subject Hello --body-text 'Hi Alice!'`

**MCP tool:** `gmail_draft`
```json
{
  "to": "alice@example.com",
  "subject": "Hello",
  "body_text": "Hi Alice!"
}
```

