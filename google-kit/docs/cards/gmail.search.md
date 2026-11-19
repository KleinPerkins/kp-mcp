# gmail.search

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/gmail.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | string | Yes | Gmail query string (e.g. 'from:boss@example.com') |
| `max_results` | integer | No | Max Results (default: 25) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | Query |
| `count` | integer | Count |
| `messages` | array | Messages |

## Performance / Quota

- api: Gmail v1
- method: users.messages.list
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail search 'from:boss@example.com'`

**MCP tool:** `gmail_search`
```json
{
  "q": "from:boss@example.com",
  "max_results": 10
}
```

