# calendar.watch

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/calendar`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `calendar_id` | string | No | Calendar Id (default: 'primary') |
| `channel_id` | string | Yes | Channel Id |
| `address` | string | Yes | Address |
| `expiration_ms` | integer | No | Expiration Ms (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `resource_id` | string | Resource Id |
| `resource_uri` | string | Resource Uri |
| `expiration` | string | Expiration |

## Performance / Quota

- api: Calendar v3
- method: events.watch
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit calendar watch --channel-id my-channel-001 --address https://example.com/webhook`

**MCP tool:** `calendar_watch`
```json
{
  "calendar_id": "primary",
  "channel_id": "my-channel-001",
  "address": "https://example.com/webhook"
}
```

