# sheets.chart

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/spreadsheets`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |
| `title` | string | Yes | Title |
| `chart_type` | string | No | Chart Type (default: 'bar') |
| `sheet_id` | integer | Yes | Sheet Id |
| `x_range` | any | Yes |  |
| `y_ranges` | array | Yes | Y Ranges |
| `stacked` | boolean | No | Stacked (default: False) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `chart_id` | integer | Chart Id |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.batchUpdate (addChart)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets chart <id> --title 'Sales Chart' --chart-type bar --sheet-id 0 --x-range '...' --y-ranges '[...]'`

**MCP tool:** `sheets_chart`
```json
{
  "spreadsheet_id": "<id>",
  "title": "Sales Chart",
  "chart_type": "bar",
  "sheet_id": 0,
  "x_range": {
    "start_row": 0,
    "end_row": 10,
    "start_col": 0,
    "end_col": 1
  },
  "y_ranges": [
    {
      "start_row": 0,
      "end_row": 10,
      "start_col": 1,
      "end_col": 2
    }
  ]
}
```

