# recipes.build_then_share

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/documents` `https://www.googleapis.com/auth/drive` `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `markdown_content` | string | Yes | Markdown body to convert into a styled Google Doc. |
| `title` | string | Yes | Title for the created Google Doc. |
| `share_with` | string | Yes | Email address (user or group) to grant access to. |
| `role` | string | No | Permission role: reader | commenter | writer. (default: 'reader') |
| `type` | string | No | Permission type: user | group | domain | anyone. (default: 'user') |
| `folder_id` | string | No | Optional Drive folder to create the Doc in. (default: None) |
| `style_profile` | string | No | Optional local Docs style profile name. (default: None) |
| `style_overrides` | object | No | Inline style profile overrides. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Status |
| `doc_id` | string | Doc Id |
| `url` | string | Url |
| `title` | string | Title |
| `shared_with` | string | Shared With |
| `role` | string | Role |

## Performance / Quota

- api: Docs v1 + Drive v3
- method: docs.from_markdown → drive.permissions.create (LIFO saga: drive.trash)
- quota: ≈4 calls/run

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit recipes build-then-share --markdown-content '# Q3 Plan' --title 'Q3 Plan' --share-with teammate@example.com --role writer`

**MCP tool:** `recipes_build_then_share`
```json
{
  "markdown_content": "# Q3 Plan\n\nDraft.",
  "title": "Q3 Plan",
  "share_with": "teammate@example.com",
  "role": "writer"
}
```
> **Note:** Saga: if sharing fails the created Doc is trashed (LIFO) and status=rolled_back is returned with meta.saga_compensated=true.

