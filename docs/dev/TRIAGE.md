# Error Triage

Error taxonomy and per-class recovery actions for google-kit operations.

## Error Classes

All google-kit errors extend `GoogleKitError`. The class name tells you what to do.

| Error class | CLI exit | When | Agent / operator action |
|-------------|----------|------|------------------------|
| `Transient` | 2 | 5xx server error | Handled automatically by `execute_api_call` (max 4 attempts, exponential backoff). Escalate if all attempts fail. |
| `Auth` | 3 | Invalid or expired token | **Stop. Do not retry.** Run `google-kit auth login` to re-authenticate. |
| `QuotaRateLimit` | 4 | Quota exhausted or rate limit hit | Wait the indicated `retry_after` seconds (default 60 s); retry once. Escalate if still failing. |
| `Permission` | 5 | Caller lacks permission | **Stop. Do not retry.** Surface to operator. Check scopes and account access. |
| `NotFound` | 6 | Resource not found | **Do not retry.** Surface the resource ID / URL to operator. |
| `Validation` | 7 | Input failed schema validation | Fix the input; retry once. Escalate if still failing. |
| `Conflict` | 8 | Duplicate or version mismatch | Do not retry without resolving the conflict. Surface to operator. |
| `Unknown` | 9 | Unclassified error | **Escalate immediately. Do not retry.** |

## MCP structured error payload

When a tool call fails, the MCP response contains:

```json
{
  "error": "<ErrorClassName>",
  "message": "<human-readable description>",
  "op": "<op.name>"
}
```

## Retry rules

- Retry: `Transient`, `QuotaRateLimit` only.
- Never retry: `Auth`, `Permission`, `NotFound`, `Unknown`.
- Retry once after fix: `Validation`, `Conflict`.
- `execute_api_call` handles `Transient` retries automatically (max 4 attempts with backoff). Agent-level retry is for `QuotaRateLimit` after `retry_after` elapses.

## Auth recovery step-by-step

1. Run `google-kit auth status` — check which keys are present.
2. If `access_token` or `refresh_token` absent: run `google-kit auth login`.
3. If `client_id` or `client_secret` absent: re-import from `client_secret.json` (see [QUICKSTART.md](../../google-kit/docs/QUICKSTART.md)).
4. Re-run the original command.

## run_id

Every error response includes `run_id` in the `meta` field. Record it for audit log correlation.
