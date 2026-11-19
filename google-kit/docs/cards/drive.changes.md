# drive.changes

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/drive.readonly` `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `page_token` | string | No | Page Token (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `changes` | array | Changes |
| `new_start_page_token` | string | New Start Page Token |

## Performance / Quota

- api: Drive v3
- method: changes.list|getStartPageToken
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive changes`

**MCP tool:** `drive_changes`
```json
{}
```

