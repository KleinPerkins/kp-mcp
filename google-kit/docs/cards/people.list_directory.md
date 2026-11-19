# people.list_directory

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/directory.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `read_mask` | string | No | Comma-separated fields to return (default: 'names,emailAddresses') |
| `sources` | array | No | Directory sources to list |
| `page_size` | integer | No | Page Size (default: 10) |
| `page_token` | string | No | Page token for continuation (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `people` | array | People |

## Performance / Quota

- api: People v1
- method: people.listDirectoryPeople
- quota: 90 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit people list-directory --page-size 10`

**MCP tool:** `people_list_directory`
```json
{
  "read_mask": "names,emailAddresses",
  "page_size": 10
}
```

