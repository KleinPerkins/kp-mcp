# docs.extract_styles

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string | Yes | Document Id |
| `style_profile` | string | No | Style Profile (default: None) |
| `template_doc_id` | string | No | Template Doc Id (default: None) |
| `tab_id` | string | No | Tab Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `document_id` | string | Document Id |
| `style_profile` | string | Style Profile |
| `profile` | object | Profile |
| `saved_path` | string | Saved Path |

## Performance / Quota

- api: Docs v1
- method: documents.get(includeTabsContent=true)
- quota: 300 req/min/user

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs extract-styles --document-id <doc-id> --style-profile default`

**MCP tool:** `docs_extract_styles`
```json
{
  "document_id": "<doc-id>",
  "style_profile": "default"
}
```
> **Note:** Local save writes config_dir/doc-styles/<name>.json with private permissions.

