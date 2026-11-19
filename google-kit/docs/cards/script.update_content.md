# script.update_content

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/script.projects`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Script Id |
| `files` | array | Yes | Files |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `script_id` | string | Script Id |
| `files` | array | Files |

## Performance / Quota

- api: Apps Script v1
- method: projects.updateContent
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script update-content --script-id <script-id> --files '[...]'`

**MCP tool:** `script_update_content`
```json
{
  "script_id": "<script-id>",
  "files": [
    {
      "name": "Code",
      "type": "SERVER_JS",
      "source": "function main() {}"
    }
  ]
}
```

