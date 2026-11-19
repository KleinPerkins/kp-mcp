# sheets.pivot

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/spreadsheets`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |
| `source_sheet_id` | integer | Yes | Source Sheet Id |
| `source_range` | any | Yes |  |
| `target_sheet_id` | integer | Yes | Target Sheet Id |
| `target_row` | integer | Yes | Target Row |
| `target_col` | integer | Yes | Target Col |
| `rows` | array | No | Rows |
| `columns` | array | No | Columns |
| `values` | array | No | Values |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `spreadsheet_id` | string | Spreadsheet Id |
| `replies_count` | integer | Replies Count |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.batchUpdate (updateCells/pivotTable)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets pivot <id> --source-sheet-id 0 ...`

**MCP tool:** `sheets_pivot`
```json
{
  "spreadsheet_id": "<id>",
  "source_sheet_id": 0,
  "source_range": {
    "start_row": 0,
    "end_row": 10,
    "start_col": 0,
    "end_col": 3
  },
  "target_sheet_id": 1,
  "target_row": 0,
  "target_col": 0,
  "rows": [
    0
  ],
  "columns": [
    1
  ],
  "values": [
    {
      "source_column_offset": 2,
      "summarize_function": "SUM"
    }
  ]
}
```

