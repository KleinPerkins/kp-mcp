# docs.styles_update

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `style_profile` | string | Yes | Style Profile |
| `updates` | object | Yes | Updates |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `style_profile` | string | Style Profile |
| `path` | string | Path |
| `deleted` | boolean | Deleted |
| `profile` | object | Profile |
| `result` | object | Result |

## Performance / Quota

- api: local filesystem
- method: merge profile JSON
- quota: n/a

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs styles-update --style-profile default --updates '{"document_style":{"documentFormat":{"documentMode":"PAGELESS"}}}'`

**MCP tool:** `docs_styles_update`
```json
{
  "style_profile": "default",
  "updates": {
    "document_style": {
      "documentFormat": {
        "documentMode": "PAGELESS"
      }
    }
  }
}
```

