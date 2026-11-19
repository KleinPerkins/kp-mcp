# drive.create

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Title |
| `doc_type` | string | No | Doc Type (default: 'doc') |
| `folder_id` | string | No | Folder Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `url` | string | Url |
| `title` | string | Title |
| `doc_type` | string | Doc Type |

## Performance / Quota

- api: Drive v3
- method: files.create
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive create 'My Doc' --type doc --folder-id <folder-id>`

**MCP tool:** `drive_create`
```json
{
  "title": "My Doc",
  "doc_type": "doc",
  "folder_id": "<folder-id>"
}
```

