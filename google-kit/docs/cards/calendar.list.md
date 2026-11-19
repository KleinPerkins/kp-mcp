# calendar.list

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/calendar.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `calendar_id` | string | No | Calendar Id (default: 'primary') |
| `time_min` | string | No | Time Min (default: None) |
| `time_max` | string | No | Time Max (default: None) |
| `max_results` | integer | No | Max Results (default: 50) |
| `days` | integer | No | Days (default: 7) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `events` | array | Events |

## Performance / Quota

- api: Calendar v3
- method: events.list
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit calendar list --days 7`

**MCP tool:** `calendar_list`
```json
{
  "calendar_id": "primary",
  "days": 7,
  "max_results": 50
}
```

