# docs.styles_repair

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `seed_default` | boolean | No | Seed Default (default: True) |

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
- method: validate/quarantine/seed profiles
- quota: n/a

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs styles-repair --seed-default true`

**MCP tool:** `docs_styles_repair`
```json
{
  "seed_default": true
}
```

