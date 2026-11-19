# tasks.update

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/tasks`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | string | Yes | Task Id |
| `tasklist` | string | No | Tasklist (default: '@default') |
| `title` | string | No | Title (default: None) |
| `notes` | string | No | Notes (default: None) |
| `due` | string | No | Due (default: None) |
| `status` | string | No | Status (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `title` | string | Title |
| `status` | string | Status |
| `due` | string | Due |

## Performance / Quota

- api: Tasks v1
- method: tasks.get + tasks.update
- quota: 1000 req/day (2 calls)

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit tasks update <task-id> --title 'New title' --due 2025-02-01`

**MCP tool:** `tasks_update`
```json
{
  "task_id": "<task-id>",
  "title": "New title",
  "due": "2025-02-01"
}
```

