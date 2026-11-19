# sheets.append

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/spreadsheets`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |
| `range` | string | Yes | Range |
| `values` | array | Yes | Values |
| `value_input_option` | string | No | Value Input Option (default: 'USER_ENTERED') |
| `insert_data_option` | string | No | Insert Data Option (default: 'INSERT_ROWS') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `updated_range` | string | Updated Range |
| `updated_rows` | integer | Updated Rows |
| `updated_columns` | integer | Updated Columns |
| `updated_cells` | integer | Updated Cells |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.values.append
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets append <id> --range Sheet1!A1 --data '[["Alice",92]]'`

**MCP tool:** `sheets_append`
```json
{
  "spreadsheet_id": "<id>",
  "range": "Sheet1!A1",
  "values": [
    [
      "Alice",
      92
    ],
    [
      "Bob",
      78
    ]
  ],
  "value_input_option": "USER_ENTERED",
  "insert_data_option": "INSERT_ROWS"
}
```

