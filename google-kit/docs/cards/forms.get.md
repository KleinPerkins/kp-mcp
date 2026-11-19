# forms.get

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/forms.body.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `form_id` | string | Yes | Form Id |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Title |
| `description` | string | Description |
| `item_count` | integer | Item Count |
| `items` | array | Items |

## Performance / Quota

- api: Forms v1
- method: forms.get
- quota: 300 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit forms get <form-id>`

**MCP tool:** `forms_get`
```json
{
  "form_id": "<form-id>"
}
```

