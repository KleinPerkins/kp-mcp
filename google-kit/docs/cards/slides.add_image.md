# slides.add_image

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/presentations`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `presentation_id` | string | Yes | Presentation Id |
| `slide_id` | string | Yes | Object ID of the target slide |
| `url` | string | Yes | Publicly accessible image URL |
| `x` | number | No | X position in inches (default: 1.0) |
| `y` | number | No | Y position in inches (default: 1.0) |
| `width` | number | No | Width in inches (default: 4.0) |
| `height` | number | No | Height in inches (default: 3.0) |
| `object_id` | string | No | Optional stable object ID override (for deterministic tests; auto-generated if omitted) (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `object_id` | string | Object Id |
| `presentation_id` | string | Presentation Id |

## Performance / Quota

- api: Slides v1
- method: presentations.batchUpdate (createImage)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit slides add-image <presentation-id> <slide-id> --url https://example.com/image.jpg`

**MCP tool:** `slides_add_image`
```json
{
  "presentation_id": "<presentation-id>",
  "slide_id": "<slide-id>",
  "url": "https://example.com/image.jpg",
  "x": 1.0,
  "y": 1.0,
  "width": 4.0,
  "height": 3.0
}
```

