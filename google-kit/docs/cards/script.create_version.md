# script.create_version

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/script.projects`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Apps Script project ID. |
| `description` | string | No | Description to store on the version. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `version` | object | Version |

## Performance / Quota

- api: Apps Script v1
- method: projects.versions.create
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script create-version --script-id <script-id> --description 'Release v1'`

**MCP tool:** `script_create_version`
```json
{
  "script_id": "<script-id>",
  "description": "Release v1"
}
```
> **Note:** Requires the off-by-default advanced scope mode AND the GOOGLE_KIT_ENABLE_SCRIPT_WRITE write gate (or the GOOGLE_KIT_ENABLE_WRITES umbrella).

