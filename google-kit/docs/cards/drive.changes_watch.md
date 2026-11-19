# drive.changes_watch

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `page_token` | string | Yes | Start page token for the change feed. |
| `channel_id` | string | Yes | Unique channel ID assigned by the operator. |
| `address` | string | Yes | HTTPS webhook URL that Drive will push to. |
| `expiration_ms` | integer | No | Optional channel expiration as Unix-epoch milliseconds. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `resourceId` | string | Resourceid |
| `resourceUri` | string | Resourceuri |
| `expiration` | string | Expiration |

## Performance / Quota

- api: Drive v3
- method: changes.watch
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive changes-watch --page-token <token> --channel-id <uuid> --address https://example.com/webhook/drive`

**MCP tool:** `drive_changes_watch`
```json
{
  "page_token": "<start-page-token>",
  "channel_id": "<uuid>",
  "address": "https://example.com/webhook/drive",
  "expiration_ms": 1735689600000
}
```
> **Note:** Drive push delivers change events to an HTTPS webhook channel; the endpoint and channel identity must be provisioned by the operator.

