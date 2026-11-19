# drive.fetch

**Posture:** read  **Scopes:** `https://www.googleapis.com/auth/drive.readonly` `https://www.googleapis.com/auth/drive.file` `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url_or_id` | string | Yes | Drive file URL or file ID; Google Sites URLs are routed to the Sites path. |
| `metadata_only` | boolean | No | Metadata Only (default: False) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `title` | string | Title |
| `mime_type` | string | Mime Type |
| `platform` | string | Platform |
| `content` | string | Content |
| `fetch_method` | string | Fetch Method |
| `web_url` | string | Web Url |

## Performance / Quota

- api: Drive v3 + Docs v1
- method: files.get + files.export
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive fetch --url-or-id 'https://docs.google.com/document/d/<id>/edit'`

**MCP tool:** `drive_fetch`
```json
{
  "url_or_id": "https://docs.google.com/document/d/<id>/edit"
}
```
> **Note:** Google Sites URLs (https://sites.google.com/...) are routed to the Sites path. Prerequisites: Chrome + browser_cookie3 + Playwright installed (see QUICKSTART.md#google-sites-prerequisites). (sandbox-e2e DEFERRED P6 is a dev parity-maturity tag for sandbox e2e test coverage, not a capability limitation.)

