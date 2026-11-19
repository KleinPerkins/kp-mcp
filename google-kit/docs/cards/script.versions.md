# script.versions

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/script.projects.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Script Id |
| `page_size` | integer | No | Max versions per page. (default: None) |
| `page_token` | string | No | Page Token (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `versions` | array | Versions |

## Performance / Quota

- api: Apps Script v1
- method: projects.versions.list
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script versions --script-id <script-id>`

**MCP tool:** `script_versions`
```json
{
  "script_id": "<script-id>"
}
```

