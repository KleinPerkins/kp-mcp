# sheets.read

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/spreadsheets.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |
| `range` | string | No | Range (default: 'Sheet1') |
| `fmt` | string | No | Fmt (default: 'json') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `range` | string | Range |
| `rows` | integer | Rows |
| `values` | array | Values |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.values.get
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets read <id> --range Sheet1!A1:C10`

**MCP tool:** `sheets_read`
```json
{
  "spreadsheet_id": "<id>",
  "range": "Sheet1!A1:C10",
  "fmt": "json"
}
```

