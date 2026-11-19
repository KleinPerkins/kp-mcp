# forms.create

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/forms.body`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Title |
| `description` | string | No | Description (default: None) |
| `document_title` | string | No | Document Title (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `form_id` | string | Form Id |
| `title` | string | Title |
| `responder_uri` | string | Responder Uri |

## Performance / Quota

- api: Forms v1
- method: forms.create + forms.batchUpdate
- quota: 300 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit forms create 'Feedback Form' --description 'Share your thoughts'`

**MCP tool:** `forms_create`
```json
{
  "title": "Feedback Form",
  "description": "Share your thoughts"
}
```

