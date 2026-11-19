# calendar.freebusy

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/calendar.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `emails` | array | Yes | Emails |
| `time_min` | string | Yes | Time Min |
| `time_max` | string | Yes | Time Max |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `time_min` | string | Time Min |
| `time_max` | string | Time Max |
| `calendars` | array | Calendars |

## Performance / Quota

- api: Calendar v3
- method: freebusy.query
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit calendar freebusy --emails alice@example.com,bob@example.com --start 2026-06-20T09:00:00 --end 2026-06-20T17:00:00`

**MCP tool:** `calendar_freebusy`
```json
{
  "emails": [
    "alice@example.com",
    "bob@example.com"
  ],
  "time_min": "2026-06-20T09:00:00Z",
  "time_max": "2026-06-20T17:00:00Z"
}
```

