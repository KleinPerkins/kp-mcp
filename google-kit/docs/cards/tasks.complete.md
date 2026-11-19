# tasks.complete

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/tasks`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | string | Yes | Task Id |
| `tasklist` | string | No | Tasklist (default: '@default') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `title` | string | Title |
| `status` | string | Status |

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

**CLI:** `google-kit tasks complete <task-id>`

**MCP tool:** `tasks_complete`
```json
{
  "task_id": "<task-id>",
  "tasklist": "@default"
}
```

