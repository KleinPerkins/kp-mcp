# recipes.template_merge

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/documents` `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `template_id` | string | Yes | Drive file ID or URL of the template document to copy. |
| `replacements` | object | Yes | Mapping of literal placeholder text → replacement value (Docs replaceAllText). |
| `new_name` | string | No | Name for the copied document. (default: None) |
| `folder_id` | string | No | Optional Drive folder for the copy. (default: None) |
| `match_case` | boolean | No | Case-sensitive placeholder matching. (default: True) |
| `style_profile` | string | No | Optional local Docs style profile to apply after merge. (default: None) |
| `style_overrides` | object | No | Inline style profile overrides. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Status |
| `doc_id` | string | Doc Id |
| `url` | string | Url |
| `name` | string | Name |
| `replacements_applied` | integer | Replacements Applied |

## Performance / Quota

- api: Drive v3 + Docs v1
- method: drive.copy → docs.batchUpdate(replaceAllText) (LIFO saga: drive.trash)
- quota: ≈2 calls/run

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit recipes template-merge --template-id <id> --new-name 'Offer — Jordan' --replacements '{"{{name}}":"Jordan"}'`

**MCP tool:** `recipes_template_merge`
```json
{
  "template_id": "<template-doc-id>",
  "new_name": "Offer \u2014 Jordan",
  "replacements": {
    "{{name}}": "Jordan",
    "{{role}}": "Engineer"
  }
}
```
> **Note:** Saga: if the merge fails the copy is trashed (LIFO) and status=rolled_back is returned.

