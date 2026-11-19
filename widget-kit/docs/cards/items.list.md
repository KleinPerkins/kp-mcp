# items.list

**Posture:** read  **Scopes:** `widget-kit:items.read`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | No | Optional filter string. |
| `limit` | integer | No | Maximum number of items to return. (default: 10) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `items` | array | Items |
| `count` | integer | Count |

## Performance / Quota

- api: Widget
- method: items.list

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `widget-kit items list --limit 5`

**MCP tool:** `items_list`
```json
{
  "limit": 5
}
```

