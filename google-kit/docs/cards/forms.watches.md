# forms.watches

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/forms.body.readonly` `https://www.googleapis.com/auth/forms.responses.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `form_id` | string | Yes | Google Forms form ID that owns the watch |
| `action` | string | No | Watch operation to perform: create, list, delete, or renew (default: 'create') |
| `topic_name` | string | No | Fully-qualified Cloud Pub/Sub topic name, e.g. projects/<project>/topics/<topic> (default: None) |
| `watch_id` | string | No | Watch ID required for delete and renew actions (default: None) |
| `event_type` | string | No | Watch event type: EVENT_TYPE_UNSPECIFIED | SCHEMA | RESPONSES (default: 'RESPONSES') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | Watch action that was executed |
| `watch_id` | string | Watch ID for create, delete, and renew actions |
| `state` | string | Watch state for create and renew actions |
| `event_type` | string | Watch event type for create and renew actions |
| `create_time` | string | Watch creation time for create and renew actions |
| `expire_time` | string | Watch expiration time for create and renew actions |
| `watches` | array | Watches returned by list |
| `count` | integer | Number of watches returned by list |
| `deleted` | boolean | True when delete completed successfully |

## Performance / Quota

- api: Forms v1
- method: forms.watches.create|list|delete|renew
- quota: 300 req/min
- note: Create requires operator-provisioned Cloud Pub/Sub topic; watches expire and must be renewed.

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit forms watches <form-id> projects/<project>/topics/<topic> --action create`

**MCP tool:** `forms_watches`
```json
{
  "form_id": "<form-id>",
  "action": "create",
  "topic_name": "projects/<project>/topics/<topic>",
  "event_type": "RESPONSES"
}
```
> **Note:** Requires Pub/Sub topic provisioning and publish permissions for the Forms service.

