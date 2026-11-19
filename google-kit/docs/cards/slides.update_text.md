# slides.update_text

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/presentations`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `presentation_id` | string | Yes | Presentation Id |
| `find` | string | No | Text to find for global case-sensitive replacement (default: None) |
| `replace` | string | No | Replacement text (used with find) (default: None) |
| `object_id` | string | No | Shape object ID for direct text update (default: None) |
| `text` | string | No | New text content (used with object_id) (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `presentation_id` | string | Presentation Id |
| `occurrences_changed` | integer | Occurrences Changed |

## Performance / Quota

- api: Slides v1
- method: presentations.batchUpdate (replaceAllText)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit slides update-text <presentation-id> --find '{{TITLE}}' --replace 'My Title'`

**MCP tool:** `slides_update_text`
```json
{
  "presentation_id": "<presentation-id>",
  "find": "{{TITLE}}",
  "replace": "My Title"
}
```

