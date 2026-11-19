# tasks.list_lists

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/tasks.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `max_results` | integer | No | Max Results (default: 100) |
| `page_token` | string | No | Continuation token from a prior page.next_page_token (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `task_lists` | array | Task Lists |

## Performance / Quota

- api: Tasks v1
- method: tasklists.list
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit tasks list-lists`

**MCP tool:** `tasks_list_lists`
```json
{
  "max_results": 100
}
```

