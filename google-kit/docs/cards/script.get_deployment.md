# script.get_deployment

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/script.projects.readonly` `https://www.googleapis.com/auth/script.deployments.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Apps Script project ID. |
| `deployment_id` | string | Yes | Deployment ID to retrieve. |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `deployment` | object | Deployment |

## Performance / Quota

- api: Apps Script v1
- method: projects.deployments.get
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script get-deployment --script-id <script-id> --deployment-id <deployment-id>`

**MCP tool:** `script_get_deployment`
```json
{
  "script_id": "<script-id>",
  "deployment_id": "<deployment-id>"
}
```

