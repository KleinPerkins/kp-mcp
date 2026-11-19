# drive.copy

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | string | Yes | File Id |
| `name` | string | No | Name (default: None) |
| `folder_id` | string | No | Folder Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `url` | string | Url |
| `name` | string | Name |

## Performance / Quota

- api: Drive v3
- method: files.copy
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive copy --file-id <file-id> --name 'Copy of Report' --folder-id <folder-id>`

**MCP tool:** `drive_copy`
```json
{
  "file_id": "<file-id>",
  "name": "Copy of Report",
  "folder_id": "<folder-id>"
}
```

