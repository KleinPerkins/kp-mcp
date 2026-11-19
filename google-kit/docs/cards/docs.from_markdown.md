# docs.from_markdown

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive` `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `markdown_content` | string | Yes | Markdown Content |
| `title` | string | Yes | Title |
| `folder_id` | string | No | Folder Id (default: None) |
| `style_profile` | string | No | Style Profile (default: None) |
| `style_overrides` | object | No | Style Overrides (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `doc_id` | string | Doc Id |
| `url` | string | Url |
| `title` | string | Title |
| `formatting_requests_applied` | integer | Formatting Requests Applied |

## Performance / Quota

- api: Drive v3 + Docs v1
- method: files.create (resumable) + documents.get + documents.batchUpdate
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs from-markdown --markdown-content '# Hello

World.' --title 'My Doc' --folder-id <folder-id>`

**MCP tool:** `docs_from_markdown`
```json
{
  "markdown_content": "# Hello\n\nWorld.",
  "title": "My Doc",
  "folder_id": "<folder-id>"
}
```
> **Note:** Formatting contract: headings → H1/H2/H3 styles, bold/italic/code preserved, margins and fonts match the legacy md-to-google-doc workflow defaults.

