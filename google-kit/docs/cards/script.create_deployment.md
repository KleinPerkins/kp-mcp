# script.create_deployment

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/script.deployments`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Apps Script project ID. |
| `version_number` | integer | No | Script version to deploy. Omit to use the Apps Script API default. (default: None) |
| `description` | string | No | Human-readable deployment description. (default: None) |
| `manifest_file_name` | string | No | Manifest file name for the deployment, typically appsscript. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `deployment` | object | Deployment |

## Performance / Quota

- api: Apps Script v1
- method: projects.deployments.create
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script create-deployment --script-id <script-id> --version-number 3 --description 'Production deployment'`

**MCP tool:** `script_create_deployment`
```json
{
  "script_id": "<script-id>",
  "version_number": 3,
  "description": "Production deployment"
}
```
> **Note:** Requires the off-by-default advanced scope mode AND the GOOGLE_KIT_ENABLE_SCRIPT_WRITE write gate (or the GOOGLE_KIT_ENABLE_WRITES umbrella).

