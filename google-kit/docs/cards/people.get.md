# people.get

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/directory.readonly` `https://www.googleapis.com/auth/contacts.readonly` `https://www.googleapis.com/auth/userinfo.profile`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `resource_name` | string | Yes | Resource name of the person, e.g. 'people/me' |
| `person_fields` | string | No | Comma-separated fields to return (default: 'names,emailAddresses') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `resource_name` | string | Resource Name |
| `names` | array | Names |
| `email_addresses` | array | Email Addresses |

## Performance / Quota

- api: People v1
- method: people.get
- quota: 90 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit people get --resource-name people/me`

**MCP tool:** `people_get`
```json
{
  "resource_name": "people/me",
  "person_fields": "names,emailAddresses"
}
```

