# drive.comments

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | string | Yes | File Id |
| `action` | string | Yes | Action |
| `content` | string | No | Content (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | Action |
| `comments` | array | Comments |
| `comment` | object | Comment |

## Performance / Quota

- api: Drive v3
- method: comments.create|list
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive comments --file-id <file-id> --action create --content 'Please review section 2.'`

**MCP tool:** `drive_comments`
```json
{
  "file_id": "<file-id>",
  "action": "create",
  "content": "Please review section 2."
}
```

