# drive.search

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/drive.readonly` `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | No | Full-text search string; maps to Drive 'fullText contains' clause. (default: None) |
| `name` | string | No | Title/name search; maps to Drive 'name contains' clause. (default: None) |
| `doc_type` | string | No | Doc Type (default: None) |
| `owner` | string | No | Owner (default: None) |
| `after` | string | No | After (default: None) |
| `before` | string | No | Before (default: None) |
| `created_after` | string | No | Created After (default: None) |
| `created_before` | string | No | Created Before (default: None) |
| `shared_with_me` | boolean | No | Shared With Me (default: False) |
| `starred` | boolean | No | Starred (default: False) |
| `scope` | string | No | Scope (default: 'allDrives') |
| `sort` | string | No | Sort (default: 'modifiedTime desc') |
| `limit` | integer | No | Limit (default: 25) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | Query |
| `count` | integer | Count |
| `results` | array | Results |
| `truncated` | boolean | Truncated |

## Performance / Quota

- api: Drive v3
- method: files.list
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive search --name 'Q1 Report' --doc-type doc --limit 10`

**MCP tool:** `drive_search`
```json
{
  "name": "Q1 Report",
  "doc_type": "doc",
  "limit": 10
}
```

