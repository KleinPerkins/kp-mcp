# docs.styles_set_default

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
- method: copy profile to default
- quota: n/a

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs styles-set-default --style-profile team`

**MCP tool:** `docs_styles_set_default`
```json
{
  "style_profile": "team"
}
```

