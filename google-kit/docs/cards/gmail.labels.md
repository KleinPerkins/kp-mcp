# gmail.labels

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| — | — | — | — |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `labels` | array | Labels |

## Performance / Quota

- api: Gmail v1
- method: users.labels.list
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail labels`

**MCP tool:** `gmail_labels`
```json
{}
```

