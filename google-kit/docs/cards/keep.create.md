# keep.create

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/keep`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Title |
| `body_text` | string | No | Body Text (default: None) |
| `list_items` | string | No | Comma-separated checklist items. If set, creates a list note instead of a text note. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Name |
| `title` | string | Title |

## Performance / Quota

- api: Keep v1
- method: notes.create
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit keep create --title 'Meeting notes' --body-text 'Q1 planning session'`

**MCP tool:** `keep_create`
```json
{
  "title": "Meeting notes",
  "body_text": "Q1 planning session"
}
```
> **Note:** BD-6: The Google Keep API is restricted and requires explicit allowlist approval from Google. The keep.* scope is NOT included in the default OAuth consent screen — a separate Workspace consent approval is required before Keep ops will succeed.

