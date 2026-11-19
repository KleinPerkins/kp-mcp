# drive.trash

**Posture:** destructive  **Scopes:** `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | string | Yes | File Id |
| `untrash` | boolean | No | Untrash (default: False) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `trashed` | boolean | Trashed |

## Performance / Quota

- api: Drive v3
- method: files.update (trashed=true/false)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive trash --file-id <file-id>`

**MCP tool:** `drive_trash`
```json
{
  "file_id": "<file-id>"
}
```

