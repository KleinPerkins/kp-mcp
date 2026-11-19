# google-kit sandbox / debug mode (E5)

A durable safe-playground for live Google calls. One env switch routes auth to a
dedicated sandbox account so debugging never touches production data. The same
switch gates the live end-to-end test harness.

## Env contract

| Var | Meaning | Default |
|-----|---------|---------|
| `GOOGLE_KIT_SANDBOX` | `1` enables sandbox mode (strict — only `1`) | unset (off) |
| `GOOGLE_KIT_SANDBOX_PROFILE` | Keychain profile holding sandbox creds | `sandbox` |

Core (`core/sandbox.py`) and the test harness (`kp_mcp_testkit.sandbox`) honor
the identical contract. They share no code (testkit stays kit-agnostic); the
agreement is locked by `google-kit/tests/test_sandbox_mode.py`.

## Runtime guardrail (durable core)

`core/sandbox.py:resolve_profile(explicit)` decides the Keychain profile, applied
at the single auth chokepoint `core/auth.py:build_service_for_op`:

| `--profile` given | `GOOGLE_KIT_SANDBOX` | Active profile |
|-------------------|----------------------|----------------|
| yes | any | the explicit profile (operator override always wins) |
| no | `1` | the sandbox profile |
| no | unset | `GOOGLE_KIT_PROFILE` / `default` (byte-identical to pre-E5) |

So in sandbox mode production is never the default; an explicit `--profile`
stays an intentional, auditable override.

## Setup

1. Provision a sandbox Google account (never a real user). Operator-approved per
   Phase -1; production is never mutated.
2. Consent the sandbox profile:
   `google-kit auth login --profile sandbox`
   New-scope APIs (Gmail-write, People directory, Drive Activity, Workspace
   Events, Apps Script) require their scopes to be consented on this profile
   before live e2e — held behind the least-privilege gate until operator sign-off.
   For the new-API + watch/subscription live suite (new scopes, Pub/Sub topic,
   and push-webhook setup), see the operator runbook
   [`LIVE-E2E-NEW-APIS.md`](./LIVE-E2E-NEW-APIS.md).
3. Enable for a shell session: `export GOOGLE_KIT_SANDBOX=1`.

## Safe-playground contract

- Production is never the default target while sandbox mode is on.
- Every created artifact is named with a `run_id` prefix for identification.
- Mutating tests create → read-back → semantic-compare → delete → verify-gone,
  with cleanup in a `finally` so a mid-test failure still tears down.
- Every run emits an audit record (`SandboxHarness.emit_audit`).

## Live test harness

`kp_mcp_testkit.sandbox` drives `google-kit/tests/test_sandbox_e2e.py`:

```python
require_sandbox()                                   # raises SandboxSkipped if off
harness = SandboxHarness(op="drive.create", run_id_prefix="p6-e2e")
ctx = harness.build_context()                       # run_id + audit record
svc = build_service_for_op("drive.create", profile=sandbox_profile())
try:
    result = drive_create(inp, service=svc)
    ctx.record_created(result.data.id)
    ctx.record_comparison(passed=..., deviation=...)
    # delete + verify gone
    ctx.record_cleaned_up()
finally:
    harness.emit_audit(ctx)
```

The harness records the run; the caller builds the service and drives the op.

## Teardown

`run_id`-prefixed artifacts make orphans greppable. Each test deletes in a
`finally`; verify nothing remains with the account's Drive/Calendar/Tasks views
filtered by the prefix, then delete any stragglers.

## CI

`uv run pytest -q` runs the sandbox suite on every push. Without
`GOOGLE_KIT_SANDBOX=1` the conftest hook converts `SandboxSkipped` into a clean
skip — no creds in CI, no failures, the harness stays continuously compiled and
import-checked.

## Run live

```bash
GOOGLE_KIT_SANDBOX=1 GOOGLE_KIT_SANDBOX_PROFILE=sandbox \
  uv run pytest google-kit/tests/test_sandbox_e2e.py -v
```
