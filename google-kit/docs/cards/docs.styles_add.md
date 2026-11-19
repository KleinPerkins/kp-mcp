# docs.styles_add

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `style_profile` | string | Yes | Style Profile |
| `document_id` | string | No | Document Id (default: None) |
| `template_doc_id` | string | No | Template Doc Id (default: None) |
| `profile_data` | object | No | Profile Data (default: None) |
| `tab_id` | string | No | Tab Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `style_profile` | string | Style Profile |
| `path` | string | Path |
| `deleted` | boolean | Deleted |
| `profile` | object | Profile |
| `result` | object | Result |

## Performance / Quota

- api: Docs v1 or local filesystem
- method: documents.get or starter template
- quota: 300 req/min/user

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs styles-add --style-profile default --document-id <doc-id>`

**MCP tool:** `docs_styles_add`
```json
{
  "style_profile": "default",
  "document_id": "<doc-id>"
}
```

