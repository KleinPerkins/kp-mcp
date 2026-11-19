# forms.publish

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/forms.body`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `form_id` | string | Yes | Form Id |
| `publish_settings` | object | Yes | Passthrough publishSettings body: keys may include publishState (PUBLISHED|UNPUBLISHED), isAcceptingResponses (bool). An updateMask is derived automatically from the provided keys. |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `form_id` | string | Form Id |
| `publish_settings` | object | Publish Settings |

## Performance / Quota

- api: Forms v1
- method: forms.setPublishSettings
- quota: 300 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit forms publish <form-id> --publish-settings '{"publishState": "PUBLISHED"}'`

**MCP tool:** `forms_publish`
```json
{
  "form_id": "<form-id>",
  "publish_settings": {
    "publishState": "PUBLISHED",
    "isAcceptingResponses": true
  }
}
```

