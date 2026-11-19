# script.get_content

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/script.projects.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Script Id |
| `version_number` | integer | No | Version number to retrieve. Omit for HEAD. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `script_id` | string | Script Id |
| `files` | array | Files |

## Performance / Quota

- api: Apps Script v1
- method: projects.getContent
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script get-content --script-id <script-id>`

**MCP tool:** `script_get_content`
```json
{
  "script_id": "<script-id>"
}
```

