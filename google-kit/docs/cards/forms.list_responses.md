# forms.list_responses

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/forms.responses.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `form_id` | string | Yes | Form Id |
| `page_size` | integer | No | Max responses per page (default: None) |
| `page_token` | string | No | Continuation token from a prior call (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `responses` | array | Responses |

## Performance / Quota

- api: Forms v1
- method: forms.responses.list
- quota: 300 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit forms list-responses <form-id>`

**MCP tool:** `forms_list_responses`
```json
{
  "form_id": "<form-id>"
}
```

