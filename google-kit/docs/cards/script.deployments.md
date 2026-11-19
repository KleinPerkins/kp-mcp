# script.deployments

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/script.projects.readonly` `https://www.googleapis.com/auth/script.deployments.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Script Id |
| `page_size` | integer | No | Max deployments per page. (default: None) |
| `page_token` | string | No | Page Token (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `deployments` | array | Deployments |

## Performance / Quota

- api: Apps Script v1
- method: projects.deployments.list
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script deployments --script-id <script-id>`

**MCP tool:** `script_deployments`
```json
{
  "script_id": "<script-id>"
}
```

