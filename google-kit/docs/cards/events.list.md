# events.list

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/drive.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `filter` | string | Yes | Filter string, e.g. 'target_resource="//drive.googleapis.com/files/<file-id>"'. |
| `page_size` | integer | No | Max subscriptions to return. (default: None) |
| `page_token` | string | No | Continuation token. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `subscriptions` | array | Subscriptions |

## Performance / Quota

- api: Workspace Events v1
- method: subscriptions.list
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit events list`

**MCP tool:** `events_list`
```json
{
  "filter": "target_resource=\"//drive.googleapis.com/files/<file-id>\""
}
```

