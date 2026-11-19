# items.create

**Posture:** write  **Scopes:** `widget-kit:items.write`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Name of the item to create. |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `name` | string | Name |

## Performance / Quota

- api: Widget
- method: items.create

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `widget-kit items create --name demo`

**MCP tool:** `items_create`
```json
{
  "name": "demo"
}
```

