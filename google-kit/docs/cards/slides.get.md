# slides.get

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/presentations.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `presentation_id` | string | Yes | Presentation Id |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `presentation_id` | string | Presentation Id |
| `title` | string | Title |
| `revision_id` | string | Revision Id |
| `url` | string | Url |
| `slide_count` | integer | Slide Count |
| `slides` | array | Slides |

## Performance / Quota

- api: Slides v1
- method: presentations.get
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit slides get <presentation-id>`

**MCP tool:** `slides_get`
```json
{
  "presentation_id": "<presentation-id>"
}
```

