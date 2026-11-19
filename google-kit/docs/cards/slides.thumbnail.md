# slides.thumbnail

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/presentations.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `presentation_id` | string | Yes | Presentation Id |
| `page_object_id` | string | Yes | Page Object Id |
| `mime_type` | string | No | Thumbnail MIME type (e.g. PNG) (default: None) |
| `thumbnail_size` | string | No | Thumbnail size: LARGE, MEDIUM, or SMALL (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `content_url` | string | Content Url |
| `width` | integer | Width |
| `height` | integer | Height |

## Performance / Quota

- api: Slides v1
- method: presentations.pages.getThumbnail
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit slides thumbnail <presentation-id> <page-object-id> --thumbnail-size LARGE`

**MCP tool:** `slides_thumbnail`
```json
{
  "presentation_id": "<presentation-id>",
  "page_object_id": "<page-object-id>",
  "thumbnail_size": "LARGE"
}
```

