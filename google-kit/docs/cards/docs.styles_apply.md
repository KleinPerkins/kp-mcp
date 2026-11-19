# docs.styles_apply

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string | Yes | Document Id |
| `style_profile` | string | No | Style Profile (default: None) |
| `style_overrides` | object | No | Style Overrides (default: None) |
| `mode` | string | No | Mode (default: 'definitions') |
| `dry_run` | boolean | No | Dry Run (default: False) |
| `tab_id` | string | No | Tab Id (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `document_id` | string | Document Id |
| `style_profile` | string | Style Profile |
| `mode` | string | Mode |
| `dry_run` | boolean | Dry Run |
| `requests` | array | Requests |
| `requests_applied` | integer | Requests Applied |
| `replies` | array | Replies |

## Performance / Quota

- api: Docs v1
- method: documents.batchUpdate(updateNamedStyle + updateDocumentStyle)
- quota: 300 req/min/user

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs styles-apply --document-id <doc-id> --style-profile default`

**MCP tool:** `docs_styles_apply`
```json
{
  "document_id": "<doc-id>",
  "style_profile": "default"
}
```

