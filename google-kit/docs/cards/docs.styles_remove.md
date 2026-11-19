# docs.styles_remove

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `style_profile` | string | Yes | Style Profile |

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
- method: delete profile JSON
- quota: n/a

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs styles-remove --style-profile old`

**MCP tool:** `docs_styles_remove`
```json
{
  "style_profile": "old"
}
```

