# tasks.delete

**Posture:** destructive  **Scopes:** `https://www.googleapis.com/auth/tasks`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | string | Yes | Task Id |
| `tasklist` | string | No | Tasklist (default: '@default') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `deleted` | boolean | Deleted |
| `task_id` | string | Task Id |

## Performance / Quota

- api: Tasks v1
- method: tasks.delete
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit tasks delete <task-id>`

**MCP tool:** `tasks_delete`
```json
{
  "task_id": "<task-id>",
  "tasklist": "@default"
}
```

