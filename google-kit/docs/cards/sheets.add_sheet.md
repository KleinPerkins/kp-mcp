# sheets.add_sheet

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/spreadsheets`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |
| `title` | string | Yes | Title |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `sheet_id` | integer | Sheet Id |
| `title` | string | Title |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.batchUpdate (addSheet)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets add-sheet <id> NewTab`

**MCP tool:** `sheets_add_sheet`
```json
{
  "spreadsheet_id": "<id>",
  "title": "NewTab"
}
```

