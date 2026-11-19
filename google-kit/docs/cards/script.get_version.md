# script.get_version

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/script.projects.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Apps Script project ID. |
| `version_number` | integer | Yes | Version number to retrieve. |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `version` | object | Version |

## Performance / Quota

- api: Apps Script v1
- method: projects.versions.get
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script get-version --script-id <script-id> --version-number 3`

**MCP tool:** `script_get_version`
```json
{
  "script_id": "<script-id>",
  "version_number": 3
}
```

