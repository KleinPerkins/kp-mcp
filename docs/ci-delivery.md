# CI and source delivery

Six closed required shards cover bootstrap/testkit, Google, Snowflake, widget, workspace cross-kit contracts and delivery. The workspace shard checks capability lock parity and regenerates all kit docs plus the catalog twice, rejecting any changed reference bytes. Live sandbox tests remain explicitly skipped without service credentials; fake API, CLI/MCP parity and safety tests execute. Product/workspace shards use standard hosted macOS for platform coverage; delivery and aggregation use standard hosted Ubuntu. Actions are commit-pinned, contents-read only, jobs bounded, and successful receipts bind exact run, attempt, tested revision, workflow and PR base/head.

Install with `uv sync --locked`; run `.venv/bin/python -I -B scripts/verify.py local`. The runner forces `GOOGLE_KIT_SANDBOX=0` so ambient live-service enrollment does not enable service access. Tests use injected native/credential fixtures; local success does not qualify hosted CI, live Keychain, service credentials or installed consumers.

The authoring agent obtains fresh independent review from the PR-creation Codex account, with separate creation witness and unedited receipt. Shared GitHub username is not account evidence. Use the qualified same-account route; missing origin/runtime blocks delivery. Chaos Scheduler App4217367 alone approves and requests exact-head native squash after first admission and actual review/CI/control qualification. Never manipulate auto-merge, bypass controls or substitute human technical review.

This successor has a new immutable repository identity. WORK source enrollment requires reviewed source, candidate hosted CI, owner-visible controls and owner initial enrollment admission; PERSONAL remains disabled pending separate qualification. After admission, admitted-main CI and repository-scoped read-only App qualification must pass before separate operational writer activation. Original private history and consumer pins remain separate; see [source boundary](source-successor.md). No App, host, credential, service or publication activation follows from these source files.

## Ordinary delivery handoff

Use the enabled WORK producer for ordinary PR creation; PERSONAL remains disabled pending separate qualification. Keep admitted-main CI and read-only App qualification records separate from the fresh ordinary PR review, creation witness and unedited receipt. Read-only qualification alone does not establish an ordinary App-owned merge.

Before writer activation, inspect owner-visible bypass actors. App-scoped omissions remain unknown, and App qualification does not attest hidden actors. Visible unexpected actors or Integration/App bypass reject activation. Retain current PR CI and receipt-admission evidence, then verify an actual App-owned ordinary squash and passing merged-revision CI before completing ordinary delivery qualification.
