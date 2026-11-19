# calendar.update

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/calendar`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | string | Yes | Event Id |
| `calendar_id` | string | No | Calendar Id (default: 'primary') |
| `summary` | string | No | Summary (default: None) |
| `description` | string | No | Description (default: None) |
| `location` | string | No | Location (default: None) |
| `start` | string | No | Start (default: None) |
| `end` | string | No | End (default: None) |
| `add_attendees` | array | No | Add Attendees |
| `timezone` | string | No | Timezone (default: 'America/New_York') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `summary` | string | Summary |
| `html_link` | string | Html Link |

## Performance / Quota

- api: Calendar v3
- method: events.get + events.patch
- quota: 1000 req/day (2 calls)

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit calendar update <event-id> --add-attendees bob@example.com`

**MCP tool:** `calendar_update`
```json
{
  "event_id": "<event-id>",
  "add_attendees": [
    "bob@example.com"
  ]
}
```

