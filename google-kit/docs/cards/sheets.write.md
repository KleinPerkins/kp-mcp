# sheets.write

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/spreadsheets`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |
| `range` | string | No | Range (default: 'Sheet1!A1') |
| `values` | array | Yes | Values |
| `clear_first` | boolean | No | Clear First (default: False) |
| `value_input_option` | string | No | Value Input Option (default: 'USER_ENTERED') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `updated_rows` | integer | Updated Rows |
| `updated_columns` | integer | Updated Columns |
| `updated_range` | string | Updated Range |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.values.update [+ values.clear]
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets write <id> --range Sheet1!A1 --data '[["A","B"],[1,2]]'`

**MCP tool:** `sheets_write`
```json
{
  "spreadsheet_id": "<id>",
  "range": "Sheet1!A1",
  "values": [
    [
      "A",
      "B"
    ],
    [
      1,
      2
    ]
  ],
  "value_input_option": "USER_ENTERED"
}
```

