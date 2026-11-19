# context.search

**Posture:** read  **Scopes:** `local:approved-context`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | Yes | Query |
| `limit` | integer | No | Limit (default: 5) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | Query |
| `revision` | string | Revision |
| `results` | array | Results |
| `count` | integer | Count |
| `truncated` | boolean | Truncated |
| `next_action` | string | Next Action |

## Performance / Quota

- source: local Git HEAD
- max_results: 10
- network_fetch: False

## Errors

| Class | When | Retry |
|-------|------|-------|
| `Validation` | The query, opaque document ID, revision, section, or limit is invalid | Correct the input; use IDs/revisions returned by context.search |
| `Unavailable` | The configured checkout, pinned blob, or bounded local Git read is unavailable | Repair setup/source state; never interpret as no matches |
| `Timeout` | Bounded local retrieval exceeds its time limit | Narrow the approved corpus or search; no automatic retry |
| `Unknown` | The failure cannot be classified safely | Escalate; do not retry automatically |
## Example

**CLI:** `snow-kit context search --query 'Example Shop return rate' --limit 5`

**MCP tool:** `context_search`
```json
{
  "query": "Example Shop return rate",
  "limit": 5
}
```

