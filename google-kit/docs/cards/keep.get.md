# keep.get

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/keep.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `note_id` | string | Yes | Note resource name, e.g. 'notes/abc123' |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Name |
| `title` | string | Title |
| `body_text` | string | Body Text |
| `create_time` | string | Create Time |
| `update_time` | string | Update Time |
| `extra` | object | Extra |

## Performance / Quota

- api: Keep v1
- method: notes.get
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit keep get notes/abc123`

**MCP tool:** `keep_get`
```json
{
  "note_id": "notes/abc123"
}
```

