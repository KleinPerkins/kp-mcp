# slides.create

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/presentations` `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Title |
| `folder_id` | string | No | Drive folder ID to move the presentation into (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `presentation_id` | string | Presentation Id |
| `url` | string | Url |
| `title` | string | Title |
| `slide_count` | integer | Slide Count |

## Performance / Quota

- api: Slides v1
- method: presentations.create (+ drive.files.update for folder)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit slides create 'My Presentation' --folder-id <folder-id>`

**MCP tool:** `slides_create`
```json
{
  "title": "My Presentation",
  "folder_id": "<folder-id>"
}
```

