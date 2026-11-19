# tasks.list

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/tasks.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tasklist` | string | No | Tasklist (default: '@default') |
| `max_results` | integer | No | Max Results (default: 100) |
| `show_completed` | boolean | No | Show Completed (default: False) |
| `due_min` | string | No | Due Min (default: None) |
| `due_max` | string | No | Due Max (default: None) |
| `page_token` | string | No | Continuation token from a prior page.next_page_token (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `tasks` | array | Tasks |

## Performance / Quota

- api: Tasks v1
- method: tasks.list
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit tasks list --tasklist @default`

**MCP tool:** `tasks_list`
```json
{
  "tasklist": "@default",
  "max_results": 100,
  "show_completed": false
}
```

