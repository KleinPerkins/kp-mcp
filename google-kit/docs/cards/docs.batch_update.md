# docs.batch_update

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/documents`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string | Yes | Document Id |
| `requests` | array | Yes | Requests |
| `write_control` | object | No | Write Control (default: None) |
| `style_profile` | string | No | Style Profile (default: None) |
| `style_overrides` | object | No | Style Overrides (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `document_id` | string | Document Id |
| `replies` | array | Replies |
| `write_control` | object | Write Control |

## Performance / Quota

- api: Docs v1
- method: documents.batchUpdate
- quota: 300 req/min/user

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit docs batch-update --document-id <doc-id> --requests '[{"insertText":{"location":{"index":1},"text":"Hello World\n"}}]'`

**MCP tool:** `docs_batch_update`
```json
{
  "document_id": "<doc-id>",
  "requests": [
    {
      "insertText": {
        "location": {
          "index": 1
        },
        "text": "Hello World\n"
      }
    }
  ]
}
```
> **Note:** Accepts any valid Docs API request object. Multiple request types may be mixed in a single call.

