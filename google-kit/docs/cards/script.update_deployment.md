# script.update_deployment

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/script.deployments`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Apps Script project ID. |
| `deployment_id` | string | Yes | Deployment ID to update. |
| `version_number` | integer | No | Script version to assign to this deployment. Omit to leave unset. (default: None) |
| `description` | string | No | Human-readable deployment description. (default: None) |
| `manifest_file_name` | string | No | Manifest file name for the deployment, typically appsscript. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `deployment` | object | Deployment |

## Performance / Quota

- api: Apps Script v1
- method: projects.deployments.update
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script update-deployment --script-id <script-id> --deployment-id <deployment-id> --version-number 4 --description 'Updated production deployment'`

**MCP tool:** `script_update_deployment`
```json
{
  "script_id": "<script-id>",
  "deployment_id": "<deployment-id>",
  "version_number": 4,
  "description": "Updated production deployment"
}
```
> **Note:** Requires the off-by-default advanced scope mode AND the GOOGLE_KIT_ENABLE_SCRIPT_WRITE write gate (or the GOOGLE_KIT_ENABLE_WRITES umbrella).

