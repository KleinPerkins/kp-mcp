# forms.get_response

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/forms.responses.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `form_id` | string | Yes | Form Id |
| `response_id` | string | Yes | Response Id |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `response_id` | string | Response Id |
| `create_time` | string | Create Time |
| `answer_count` | integer | Answer Count |
| `answers` | array | Answers |

## Performance / Quota

- api: Forms v1
- method: forms.responses.get
- quota: 300 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit forms get-response <form-id> <response-id>`

**MCP tool:** `forms_get_response`
```json
{
  "form_id": "<form-id>",
  "response_id": "<response-id>"
}
```

