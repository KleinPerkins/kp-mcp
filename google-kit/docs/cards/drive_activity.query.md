# drive_activity.query

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/drive.activity.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `item_name` | string | No | Item name to filter by, e.g. 'items/FILE_ID' (default: None) |
| `ancestor_name` | string | No | Ancestor folder name to filter by, e.g. 'items/FOLDER_ID' (default: None) |
| `filter` | string | No | Filter string (time + detail.action_detail_case filters) (default: None) |
| `consolidation_strategy` | string | No | Consolidation strategy: 'legacy' or 'none' (default: None) |
| `page_size` | integer | No | Page Size (default: None) |
| `page_token` | string | No | Page Token (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `activities` | array | Activities |

## Performance / Quota

- api: Drive Activity v2
- method: activity.query
- quota: 1000 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive_activity query --item-name items/FILE_ID`

**MCP tool:** `drive_activity_query`
```json
{
  "item_name": "items/FILE_ID"
}
```

