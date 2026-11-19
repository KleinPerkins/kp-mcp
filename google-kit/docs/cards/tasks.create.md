# tasks.create

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/tasks`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Title |
| `tasklist` | string | No | Tasklist (default: '@default') |
| `notes` | string | No | Notes (default: None) |
| `due` | string | No | Due (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `title` | string | Title |
| `status` | string | Status |
| `due` | string | Due |

## Performance / Quota

- api: Tasks v1
- method: tasks.insert
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit tasks create 'Buy milk' --due 2025-01-15`

**MCP tool:** `tasks_create`
```json
{
  "title": "Buy milk",
  "tasklist": "@default",
  "due": "2025-01-15"
}
```

