# slides.add_slide

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/presentations`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `presentation_id` | string | Yes | Presentation Id |
| `layout` | string | No | Predefined layout name (e.g. BLANK, TITLE, TITLE_AND_BODY) (default: 'BLANK') |
| `insert_at` | integer | No | 0-based insertion index; appends if omitted (default: None) |
| `title_text` | string | No | Text to insert into the TITLE placeholder (default: None) |
| `body_text` | string | No | Text to insert into the BODY placeholder (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `slide_id` | string | Slide Id |
| `presentation_id` | string | Presentation Id |

## Performance / Quota

- api: Slides v1
- method: presentations.batchUpdate (createSlide)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit slides add-slide <presentation-id>`

**MCP tool:** `slides_add_slide`
```json
{
  "presentation_id": "<presentation-id>",
  "layout": "BLANK"
}
```

