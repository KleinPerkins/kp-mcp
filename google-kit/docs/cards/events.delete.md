# events.delete

**Posture:** destructive  **Scopes:** `https://www.googleapis.com/auth/drive.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Subscription resource name to delete. |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Name |
| `done` | boolean | Done |

## Performance / Quota

- api: Workspace Events v1
- method: subscriptions.delete
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit events delete`

**MCP tool:** `events_delete`
```json
{
  "name": "subscriptions/<subscription-id>"
}
```

