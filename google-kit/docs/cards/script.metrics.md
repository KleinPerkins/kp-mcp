# script.metrics

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/script.metrics`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Script Id |
| `metrics_granularity` | string | Yes | Granularity of returned metrics: WEEKLY or DAILY. |
| `metrics_filter_deployment_id` | string | No | Limit metrics to a specific deployment ID. Optional. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `active_users` | array | Active Users |
| `total_executions` | array | Total Executions |
| `failed_executions` | array | Failed Executions |

## Performance / Quota

- api: Apps Script v1
- method: projects.getMetrics
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script metrics --script-id <script-id> --metrics-granularity WEEKLY`

**MCP tool:** `script_metrics`
```json
{
  "script_id": "<script-id>",
  "metrics_granularity": "WEEKLY"
}
```

