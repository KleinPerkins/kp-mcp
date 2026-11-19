# gmail.manage_labels

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/gmail.modify`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Display name of the new label |
| `label_list_visibility` | string | No | Label visibility in the label list (labelShow | labelShowIfUnread | labelHide) (default: 'labelShow') |
| `message_list_visibility` | string | No | Message visibility in the message list (show | hide) (default: 'show') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `label_id` | string | ID of the newly created label |
| `name` | string | Display name of the created label |

## Performance / Quota

- api: Gmail v1
- method: users.labels.create
- quota: 250 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit gmail manage-labels --name ProjectX`

**MCP tool:** `gmail_manage_labels`
```json
{
  "name": "ProjectX"
}
```

