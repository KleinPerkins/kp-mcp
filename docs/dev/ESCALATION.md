# Escalation and Deviation Policy

When an agent must stop and request operator approval vs when it may proceed autonomously.

## Autonomous-resolution (no approval needed)

An agent MAY act without operator approval for:

- Letting `execute_api_call` handle `Transient` retries automatically (max 4 attempts, exponential backoff); agent adds no retry loop for `Transient`.
- Retrying `QuotaRateLimit` after the indicated wait (once).
- Running `google-kit auth login` on `Auth` error.
- Fixing `Validation` errors by adjusting input to the declared schema.
- Invoking any `read`-posture tool without confirmation.
- Making strictly additive optional-field changes (logged, auto-approved).

## Escalation required

Stop and request explicit operator approval for:

- **Destructive ops** (`posture: destructive`): e.g. `calendar.delete`, `tasks.delete`, `keep.delete`.
- **Write ops** (`posture: write`): confirmation required before the first mutation in a session.
- **Scope expansion**: any new OAuth scope not approved in Phase -1.
- **Non-trivial parity deviation**: output differs from legacy in a non-cosmetic way.
- **`Unknown` errors**: any unclassified failure.
- **Persistent `Transient` failures**: after `execute_api_call` exhausts all 4 attempts.
- **`Permission` or `NotFound` errors**: surface but do not retry.

## Destructive-op protocol

1. Display the exact operation name and target IDs to the operator.
2. Wait for explicit "yes, proceed" confirmation **in the current turn**.
3. Execute **at most once**; never loop destructive ops without re-confirming.
4. Record the `run_id` from the response for audit traceability.

## Deviation policy

| Deviation type | Classification | Action |
|---------------|----------------|--------|
| Cosmetic formatting | Trivial | Auto-approved; logged |
| Strictly additive optional fields | Trivial | Auto-approved; logged |
| Identical semantics under normalized output | Trivial | Auto-approved; logged |
| Different output structure or values | Non-trivial | Stop; log deviation; request operator approval |
| Missing field vs legacy | Non-trivial | Stop; log; request approval |
| Behavior difference (e.g. BD-1 drive.upload) | Non-trivial | Document in MIGRATION-DRYRUN; request approval |

## Escalation format

When escalating, provide:

1. The operation (`op.name`) and target IDs.
2. The error class or deviation description.
3. The `run_id` for log correlation.
4. The exact approval or decision needed.

Do not proceed until the operator responds.
