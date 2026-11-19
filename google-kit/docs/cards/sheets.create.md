# sheets.create

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/spreadsheets` `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Title |
| `sheet_names` | array | No | Sheet Names |
| `folder_id` | string | No | Folder Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `spreadsheet_id` | string | Spreadsheet Id |
| `url` | string | Url |
| `title` | string | Title |
| `sheets` | array | Sheets |

## Performance / Quota

- api: Sheets v4 + Drive v3
- method: spreadsheets.create [+ files.update]
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit sheets create 'My Sheet' --sheet-names Data,Summary --folder-id <folder-id>`

**MCP tool:** `sheets_create`
```json
{
  "title": "My Sheet",
  "sheet_names": [
    "Data",
    "Summary"
  ],
  "folder_id": "<folder-id>"
}
```

