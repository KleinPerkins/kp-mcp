# forms.add_item

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/forms.body`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `form_id` | string | Yes | Form Id |
| `title` | string | Yes | Title |
| `item_type` | string | No | Item Type (default: 'short_text') |
| `options` | string | No | Comma-separated option values (required for multiple_choice, checkbox, dropdown) (default: None) |
| `required` | boolean | No | Required (default: False) |
| `index` | integer | No | Position index (0 = first) (default: 0) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `form_id` | string | Form Id |
| `item_type` | string | Item Type |
| `index` | integer | Index |

## Performance / Quota

- api: Forms v1
- method: forms.batchUpdate (createItem)
- quota: 300 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit forms add-item <form-id> 'Rate your experience' --type scale`

**MCP tool:** `forms_add_item`
```json
{
  "form_id": "<form-id>",
  "title": "Rate your experience",
  "item_type": "scale"
}
```

