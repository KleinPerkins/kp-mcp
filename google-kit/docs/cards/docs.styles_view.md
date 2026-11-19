# docs.styles_view

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `style_profile` | string | No | Style Profile (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `profiles` | array | Profiles |
| `default` | string | Default |
| `selected` | string | Selected |
| `profile` | object | Profile |

## Performance / Quota

- api: local filesystem
- method: read config_dir/doc-styles
- quota: n/a

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs styles-view`

**MCP tool:** `docs_styles_view`
```json
{}
```

