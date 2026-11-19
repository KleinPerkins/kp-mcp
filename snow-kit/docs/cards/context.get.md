# context.get

**Posture:** read  **Scopes:** `local:approved-context`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string | Yes | Document Id |
| `revision` | string | Yes | Revision |
| `section` | string | No | Section (default: None) |
| `max_chars` | integer | No | Max Chars (default: 6000) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `document_id` | string | Document Id |
| `title` | string | Title |
| `section` | string | Section |
| `content` | string | Content |
| `truncated` | boolean | Truncated |
| `authority` | string | Authority |
| `metadata_complete` | boolean | Metadata Complete |
| `provenance` | object | ContextProvenance |

## Performance / Quota

- source: local Git commit
- max_chars: 12000
- network_fetch: False

## Errors

| Class | When | Retry |
|-------|------|-------|
| `Validation` | The query, opaque document ID, revision, section, or limit is invalid | Correct the input; use IDs/revisions returned by context.search |
| `Unavailable` | The configured checkout, pinned blob, or bounded local Git read is unavailable | Repair setup/source state; never interpret as no matches |
| `Timeout` | Bounded local retrieval exceeds its time limit | Narrow the approved corpus or search; no automatic retry |
| `Unknown` | The failure cannot be classified safely | Escalate; do not retry automatically |
## Example

**CLI:** `snow-kit context get --document-id <id> --revision <sha> --section 'Data Sources & Joins'`

**MCP tool:** `context_get`
```json
{
  "document_id": "0123456789abcdef01234567",
  "revision": "0123456789abcdef0123456789abcdef01234567",
  "section": "Data Sources & Joins"
}
```

