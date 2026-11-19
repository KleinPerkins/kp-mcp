# recipes.build_styled

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/documents` `https://www.googleapis.com/auth/drive` `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `markdown_content` | string | Yes | Markdown body to convert into a styled Google Doc. |
| `title` | string | Yes | Title for the created Google Doc. |
| `folder_id` | string | No | Optional Drive folder to create the Doc in. (default: None) |
| `style_profile` | string | No | Local Docs style profile name. (default: None) |
| `style_overrides` | object | No | Inline style profile overrides. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Status |
| `doc_id` | string | Doc Id |
| `url` | string | Url |
| `title` | string | Title |
| `style_requests_applied` | integer | Style Requests Applied |

## Performance / Quota

- api: Docs v1 + Drive v3
- method: docs.from_markdown → docs.apply_styles (LIFO saga: drive.trash)
- quota: ≈4 calls/run

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit recipes build-styled --markdown-content '# Styled Plan' --title 'Styled Plan' --style-profile default`

**MCP tool:** `recipes_build_styled`
```json
{
  "markdown_content": "# Styled Plan\n\nDraft.",
  "title": "Styled Plan",
  "style_profile": "default"
}
```
> **Note:** Saga: if style application fails, the created Doc is trashed (LIFO).

