# script.run

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/script.projects` `https://www.googleapis.com/auth/script.external_request`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `script_id` | string | Yes | Script Id |
| `function` | string | Yes | Name of the function to run. |
| `parameters` | array | No | Arguments to pass to the function. (default: None) |
| `dev_mode` | boolean | No | Run the head deployment instead of the latest. Optional. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `done` | boolean | Done |
| `response` | object | Response |
| `error` | object | Error |

## Performance / Quota

- api: Apps Script v1
- method: scripts.run
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit script run --script-id <script-id> --function myFunction`

**MCP tool:** `script_run`
```json
{
  "script_id": "<script-id>",
  "function": "myFunction"
}
```
> **Note:** Escape-hatch only — requires the script deployed as API-executable in the same Cloud project as the OAuth client. Gated by GOOGLE_KIT_ENABLE_SCRIPT_WRITE (or the GOOGLE_KIT_ENABLE_WRITES umbrella).

