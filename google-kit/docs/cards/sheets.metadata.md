# sheets.metadata

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/spreadsheets`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spreadsheet_id` | string | Yes | Spreadsheet Id |
| `metadata_key` | string | Yes | Metadata Key |
| `metadata_value` | string | Yes | Metadata Value |
| `visibility` | string | No | Visibility (default: 'DOCUMENT') |
| `location_sheet_id` | integer | No | Location Sheet Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `spreadsheet_id` | string | Spreadsheet Id |
| `replies_count` | integer | Replies Count |

## Performance / Quota

- api: Sheets v4
- method: spreadsheets.batchUpdate (createDeveloperMetadata)
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets metadata <id> --key project --value alpha`

**MCP tool:** `sheets_metadata`
```json
{
  "spreadsheet_id": "<id>",
  "metadata_key": "project",
  "metadata_value": "alpha",
  "visibility": "DOCUMENT"
}
```

