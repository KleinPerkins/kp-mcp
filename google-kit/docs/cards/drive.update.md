# drive.update

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | string | Yes | File Id |
| `name` | string | No | Name (default: None) |
| `description` | string | No | Description (default: None) |
| `starred` | boolean | No | Starred (default: None) |
| `add_parents` | array | No | Add Parents (default: None) |
| `remove_parents` | array | No | Remove Parents (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `name` | string | Name |
| `parents` | array | Parents |

## Performance / Quota

- api: Drive v3
- method: files.update
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive update --file-id <file-id> --name 'New Name'`

**MCP tool:** `drive_update`
```json
{
  "file_id": "<file-id>",
  "name": "New Name"
}
```

