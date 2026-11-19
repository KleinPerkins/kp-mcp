# people.search_directory

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/directory.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | Yes | Search query string |
| `read_mask` | string | No | Comma-separated fields to return (default: 'names,emailAddresses') |
| `sources` | array | No | Directory sources to search |
| `page_size` | integer | No | Page Size (default: 10) |
| `page_token` | string | No | Page token for continuation (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Count |
| `people` | array | People |

## Performance / Quota

- api: People v1
- method: people.searchDirectoryPeople
- quota: 90 req/min

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit people search-directory --query Alice`

**MCP tool:** `people_search_directory`
```json
{
  "query": "Alice"
}
```

