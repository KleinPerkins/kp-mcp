# drive.revisions

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/drive.readonly` `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | string | Yes | File Id |
| `revision_id` | string | No | Revision Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `revisions` | array | Revisions |
| `revision` | object | Revision |

## Performance / Quota

- api: Drive v3
- method: revisions.list|get
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive revisions --file-id <file-id>`

**MCP tool:** `drive_revisions`
```json
{
  "file_id": "<file-id>"
}
```

