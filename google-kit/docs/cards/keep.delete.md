# keep.delete

**Posture:** destructive  **Scopes:** `https://www.googleapis.com/auth/keep`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `note_id` | string | Yes | Note resource name, e.g. 'notes/abc123' |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `deleted` | boolean | Deleted |
| `note_id` | string | Note Id |

## Performance / Quota

- api: Keep v1
- method: notes.delete
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit keep delete --note-id notes/abc123`

**MCP tool:** `keep_delete`
```json
{
  "note_id": "notes/abc123"
}
```
> **Note:** BD-6: The Google Keep API is restricted and requires explicit allowlist approval from Google. The keep.* scope is NOT included in the default OAuth consent screen — a separate Workspace consent approval is required before Keep ops will succeed.

