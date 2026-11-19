# drive.permissions

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_id` | string | Yes | File Id |
| `action` | string | Yes | Action |
| `role` | string | No | Role (default: None) |
| `type` | string | No | Type (default: None) |
| `email_address` | string | No | Email Address (default: None) |
| `domain` | string | No | Domain (default: None) |
| `permission_id` | string | No | Permission Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | Action |
| `permissions` | array | Permissions |
| `permission` | object | Permission |
| `deleted` | boolean | Deleted |

## Performance / Quota

- api: Drive v3
- method: permissions.create|list|delete
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive permissions --file-id <file-id> --action create --type user --role reader --email-address user@example.com`

**MCP tool:** `drive_permissions`
```json
{
  "file_id": "<file-id>",
  "action": "create",
  "type": "user",
  "role": "reader",
  "email_address": "user@example.com"
}
```

