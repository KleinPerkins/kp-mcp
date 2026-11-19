# sheets.conditional_format

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/spreadsheets`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |
| `sheet_id` | integer | Yes | Sheet Id |
| `range` | any | Yes |  |
| `condition_type` | string | Yes | Condition Type |
| `condition_values` | array | Yes | Condition Values |
| `background_color` | any | No |  (default: None) |
| `bold` | boolean | No | Bold (default: None) |
| `index` | integer | No | Index (default: 0) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `spreadsheet_id` | string | Spreadsheet Id |
| `replies_count` | integer | Replies Count |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.batchUpdate (addConditionalFormatRule)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets conditional-format <id> --sheet-id 0 ...`

**MCP tool:** `sheets_conditional_format`
```json
{
  "spreadsheet_id": "<id>",
  "sheet_id": 0,
  "range": {
    "start_row": 1,
    "end_row": 100,
    "start_col": 2,
    "end_col": 3
  },
  "condition_type": "NUMBER_GREATER",
  "condition_values": [
    "100"
  ],
  "background_color": {
    "red": 1.0,
    "green": 0.0,
    "blue": 0.0
  },
  "bold": true
}
```

