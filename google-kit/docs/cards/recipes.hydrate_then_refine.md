# recipes.hydrate_then_refine

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/documents` `https://www.googleapis.com/auth/drive.file` `https://www.googleapis.com/auth/drive.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string | Yes | Drive/Docs file ID or URL to hydrate then refine. |
| `requests` | array | Yes | Docs API batchUpdate request objects to apply as the refinement. |
| `hydrate_metadata_only` | boolean | No | Hydrate via a metadata-only fetch (no full content export). (default: True) |
| `style_profile` | string | No | Optional local Docs style profile to append to the refinement. (default: None) |
| `style_overrides` | object | No | Inline style profile overrides. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Status |
| `doc_id` | string | Doc Id |
| `title` | string | Title |
| `mime_type` | string | Mime Type |
| `requests_applied` | integer | Requests Applied |
| `refine_replies` | array | Refine Replies |

## Performance / Quota

- api: Drive v3 + Docs v1
- method: drive.fetch → docs.batchUpdate
- quota: ≈2 calls/run

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit recipes hydrate-then-refine --document-id <id> --requests '[{"insertText":{"location":{"index":1},"text":"Summary\n"}}]'`

**MCP tool:** `recipes_hydrate_then_refine`
```json
{
  "document_id": "<doc-id>",
  "requests": [
    {
      "insertText": {
        "location": {
          "index": 1
        },
        "text": "Summary\n"
      }
    }
  ]
}
```
> **Note:** Hydrate is read-only (no compensation); refine applies the requests. A refine failure leaves no mutation to roll back.

