# sheets.info

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/spreadsheets.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Title |
| `spreadsheet_id` | string | Spreadsheet Id |
| `url` | string | Url |
| `sheets` | array | Sheets |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.get
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets info <id>`

**MCP tool:** `sheets_info`
```json
{
  "spreadsheet_id": "<id>"
}
```

