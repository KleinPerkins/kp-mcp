# script.create

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/script.projects`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Title for the new script project. |
| `parent_id` | string | No | Drive item ID of the parent (e.g. a Google Doc). Optional. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `script_id` | string | Script Id |
| `title` | string | Title |

## Performance / Quota

- api: Apps Script v1
- method: projects.create
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script create --title 'My Automation Script'`

**MCP tool:** `script_create`
```json
{
  "title": "My Automation Script"
}
```

