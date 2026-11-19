# gmail.profile

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| — | — | — | — |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `email_address` | string | Always '[REDACTED]' — PII not emitted |
| `messages_total` | integer | Messages Total |
| `threads_total` | integer | Threads Total |

## Performance / Quota

- api: Gmail v1
- method: users.getProfile
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail profile`

**MCP tool:** `gmail_profile`
```json
{}
```

