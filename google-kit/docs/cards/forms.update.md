# forms.update

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/forms.body`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `form_id` | string | Yes | Form Id |
| `title` | string | No | Title (default: None) |
| `description` | string | No | Description (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `form_id` | string | Form Id |
| `updated_fields` | array | Updated Fields |

## Performance / Quota

- api: Forms v1
- method: forms.batchUpdate (updateFormInfo)
- quota: 300 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit forms update <form-id> --title 'Updated Title'`

**MCP tool:** `forms_update`
```json
{
  "form_id": "<form-id>",
  "title": "Updated Title",
  "description": "New description"
}
```

