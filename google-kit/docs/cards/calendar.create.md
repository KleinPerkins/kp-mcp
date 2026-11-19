# calendar.create

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/calendar`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `summary` | string | Yes | Summary |
| `start` | string | Yes | Start |
| `end` | string | No | End (default: None) |
| `duration` | integer | No | Duration (default: 30) |
| `description` | string | No | Description (default: None) |
| `location` | string | No | Location (default: None) |
| `attendees` | array | No | Attendees |
| `meet` | boolean | No | Meet (default: False) |
| `all_day` | boolean | No | All Day (default: False) |
| `timezone` | string | No | Timezone (default: 'America/New_York') |
| `calendar_id` | string | No | Calendar Id (default: 'primary') |
| `conference_request_id` | string | No | Conference Request Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `summary` | string | Summary |
| `html_link` | string | Html Link |
| `hangout_link` | string | Hangout Link |
| `start` | object | Start |

## Performance / Quota

- api: Calendar v3
- method: events.insert
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit calendar create 'Team Meeting' --start 2026-06-20T10:00:00 --end 2026-06-20T11:00:00 --meet`

**MCP tool:** `calendar_create`
```json
{
  "summary": "Team Meeting",
  "start": "2026-06-20T10:00:00",
  "end": "2026-06-20T11:00:00",
  "meet": true
}
```

