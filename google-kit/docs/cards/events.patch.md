# events.patch

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Subscription resource name to patch. |
| `update_mask` | string | No | Comma-separated field mask. (default: 'ttl') |
| `ttl` | string | No | New TTL duration string, e.g. '3600s'. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Name |
| `done` | boolean | Done |

## Performance / Quota

- api: Workspace Events v1
- method: subscriptions.patch
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit events patch`

**MCP tool:** `events_patch`
```json
{
  "name": "subscriptions/<subscription-id>",
  "ttl": "3600s"
}
```

