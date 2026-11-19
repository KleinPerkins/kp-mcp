# calendar.delete

**Posture:** destructive  **Scopes:** `https://www.googleapis.com/auth/calendar`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | string | Yes | Event Id |
| `calendar_id` | string | No | Calendar Id (default: 'primary') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `deleted` | boolean | Deleted |
| `event_id` | string | Event Id |

## Performance / Quota

- api: Calendar v3
- method: events.delete
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit calendar delete <event-id>`

**MCP tool:** `calendar_delete`
```json
{
  "event_id": "<event-id>",
  "calendar_id": "primary"
}
```

