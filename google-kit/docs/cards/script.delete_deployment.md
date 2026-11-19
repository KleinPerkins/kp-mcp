# script.delete_deployment

**Posture:** destructive  **Scopes:** `https://www.googleapis.com/auth/script.deployments`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Apps Script project ID. |
| `deployment_id` | string | Yes | Deployment ID to delete. |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `deleted` | boolean | Deleted |
| `response` | object | Response |

## Performance / Quota

- api: Apps Script v1
- method: projects.deployments.delete
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script delete-deployment --script-id <script-id> --deployment-id <deployment-id>`

**MCP tool:** `script_delete_deployment`
```json
{
  "script_id": "<script-id>",
  "deployment_id": "<deployment-id>"
}
```
> **Note:** Requires the off-by-default advanced scope mode AND the GOOGLE_KIT_ENABLE_SCRIPT_WRITE write gate (or the GOOGLE_KIT_ENABLE_WRITES umbrella).

