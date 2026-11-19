# gmail.attachments

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message_id` | string | Yes | Gmail message ID containing the attachment |
| `attachment_id` | string | Yes | Attachment part ID (from message payload.parts[].body.attachmentId) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `attachment_id` | string | Attachment Id |
| `size` | integer | Size |
| `data_b64` | string | URL-safe base64-encoded attachment content |

## Performance / Quota

- api: Gmail v1
- method: users.messages.attachments.get
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail attachments --message-id msg001abc --attachment-id ANGjdJ8abc123`

**MCP tool:** `gmail_attachments`
```json
{
  "message_id": "msg001abc",
  "attachment_id": "ANGjdJ8abc123"
}
```

