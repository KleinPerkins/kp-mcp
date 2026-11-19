# Doc-Comprehension Task Suite

Machine-readable companion: [`doc_task_suite.json`](doc_task_suite.json)  
Exit gate (B13): 100% task success / zero clarifying questions / cap 25 iterations.

## Suite Overview

42 tasks across 7 categories. Each task is given only the listed context paths — no source code.

| # | ID | Category | Context |
|---|----|----------|---------|
| 1 | `install-bootstrap` | Install / Bootstrap | QUICKSTART |
| 2 | `auth-prerequisites` | Auth | QUICKSTART |
| 3 | `auth-login` | Auth | QUICKSTART |
| 4 | `auth-status` | Auth | QUICKSTART |
| 5 | `auth-logout` | Auth | QUICKSTART |
| 6 | `auth-login-force` | Auth | QUICKSTART |
| 7 | `auth-headless` | Auth | QUICKSTART |
| 8 | `drive-fetch-cli` | Legacy workflow (Group A/B/D) | INDEX |
| 9 | `drive-search-cli` | Legacy workflow (Group P) | INDEX |
| 10 | `drive-upload-cli` | Legacy workflow (BD-1) | INDEX |
| 11 | `drive-create-cli` | Legacy workflow | INDEX |
| 12 | `docs-from-markdown-cli` | Legacy workflow (Group D) | INDEX |
| 13 | `gmail-list-cli` | Legacy workflow (Groups K) | INDEX |
| 14 | `gmail-get-cli` | Legacy workflow (Group L) | INDEX |
| 15 | `gmail-search-cli` | Legacy workflow (Group M) | INDEX |
| 16 | `gmail-profile-mcp` | Legacy workflow (Groups E/J/O) | INDEX |
| 17 | `calendar-list-cli` | Legacy workflow | INDEX |
| 18 | `calendar-create-mcp` | Representative write | INDEX |
| 19 | `calendar-freebusy-cli` | Legacy workflow | INDEX |
| 20 | `calendar-delete-cli` | Representative destructive | INDEX |
| 21 | `sheets-read-cli` | Legacy workflow | INDEX |
| 22 | `sheets-write-mcp` | Representative write | INDEX |
| 23 | `sheets-create-cli` | Legacy workflow | INDEX |
| 24 | `slides-create-cli` | Legacy workflow | INDEX |
| 25 | `slides-add-slide-mcp` | Representative write | INDEX |
| 26 | `forms-create-cli` | Legacy workflow | INDEX |
| 27 | `forms-list-responses-cli` | Legacy workflow | INDEX |
| 28 | `tasks-list-lists-cli` | Legacy workflow | INDEX |
| 29 | `tasks-create-cli` | Legacy workflow (Group R) | INDEX |
| 30 | `tasks-delete-mcp` | Representative destructive | INDEX |
| 31 | `keep-create-cli` | Legacy workflow | INDEX |
| 32 | `keep-delete-cli` | Representative destructive | INDEX |
| 33 | `add-capability` | Adding a capability | SERVICE-PATTERN |
| 34 | `triage-transient` | Error triage | INDEX |
| 35 | `triage-auth` | Error triage | INDEX |
| 36 | `triage-quota` | Error triage | INDEX |
| 37 | `triage-permission` | Error triage | INDEX |
| 38 | `triage-notfound` | Error triage | INDEX |
| 39 | `triage-validation` | Error triage | INDEX |
| 40 | `triage-unknown` | Error triage | INDEX |
| 41 | `escalation-destructive` | Escalation | INDEX |
| 42 | `escalation-deviation` | Escalation / deviation | INDEX |
| 43 | `run-id-audit` | Observability | INDEX |

**Total: 43 tasks**

## Task Definitions

### Install / Bootstrap

**`install-bootstrap`**  
Context: `google-kit/docs/QUICKSTART.md`  
Task: Explain installation and the qualified owner registration workflow. Source 0.3.0 has no live writer qualification, so the live registration portion is blocked. Do not run bootstrap as an implicit write.

Success: After separate native qualification and exact operation approval, verify the owner workflow registered the Cursor entry and authentication remains separately unverified. A bounded refusal or source/fixture test does not pass this live doc-loop task.

### Auth

**`auth-prerequisites`**  
Context: `google-kit/docs/QUICKSTART.md`  
Task: What prerequisites must be in the Keychain before `google-kit auth login`? Provide exact `security add-generic-password` commands.  
Success: Produces exact commands for client_id and client_secret without source code.

**`auth-login`**  
Context: `google-kit/docs/QUICKSTART.md`  
Task: Run `google-kit auth login`. Describe the full flow, what gets stored, success output.  
Success: PKCE loopback; tokens in Keychain under profile 'default'; success output shows 'Login successful'.

**`auth-status`**  
Context: `google-kit/docs/QUICKSTART.md`  
Task: How do you verify authentication? Show command; interpret logged-in vs not-logged-in output.  
Success: `google-kit auth status`; exit 0 when token present, exit 1 + hint when absent.

**`auth-logout`**  
Context: `google-kit/docs/QUICKSTART.md`  
Task: Log out removing tokens but keeping client credentials. Then show how to remove everything.  
Success: `google-kit auth logout` (tokens only); `google-kit auth logout --all` (everything).

**`auth-login-force`**  
Context: `google-kit/docs/QUICKSTART.md`  
Task: Force re-consent when a valid token exists. What replaces `refresh_google_oauth.py --force`?  
Success: `google-kit auth login --force`.

**`auth-headless`**  
Context: `google-kit/docs/QUICKSTART.md`  
Task: Authenticate on a headless server (no browser).  
Success: `google-kit auth login --headless`; auth URL printed to stderr.

### Legacy Workflow Migration

**`drive-fetch-cli`** — `google-kit drive fetch --url-or-id <url>`  
**`drive-search-cli`** — `google-kit drive search --query <q>` + MCP `drive_search`  
**`drive-upload-cli`** — `google-kit drive upload --file <path>` (note BD-1 behavior restore)  
**`drive-create-cli`** — `google-kit drive create --title <t> --type <sheet|doc>`  
**`docs-from-markdown-cli`** — `google-kit docs from-markdown --file <path>` (note formatting contract)  
**`gmail-list-cli`** — `google-kit gmail list [--max-results N] [--label-ids L]`  
**`gmail-get-cli`** — `google-kit gmail get --thread-id <id>` (note 500-char body truncation)  
**`gmail-search-cli`** — `google-kit gmail search --query <q>` (lighter payload than list)  
**`gmail-profile-mcp`** — MCP tool `gmail_profile` (no required args)  
**`calendar-list-cli`** — `google-kit calendar list --days N`  
**`calendar-create-mcp`** — MCP `calendar_create` with summary/start/duration/meet  
**`calendar-freebusy-cli`** — `google-kit calendar freebusy --emails <...> --start <t> --end <t>`  
**`calendar-delete-cli`** — destructive; confirmation required before each call  
**`sheets-read-cli`** — `google-kit sheets read --spreadsheet-id <id> --range <A1:C10>`  
**`sheets-write-mcp`** — MCP `sheets_write` with spreadsheet_id/range/values  
**`sheets-create-cli`** — `google-kit sheets create --title <t>`  
**`slides-create-cli`** — `google-kit slides create --title <t>`  
**`slides-add-slide-mcp`** — MCP `slides_add_slide`  
**`forms-create-cli`** — `google-kit forms create --title <t>`  
**`forms-list-responses-cli`** — `google-kit forms list-responses --form-id <id>`  
**`tasks-list-lists-cli`** — `google-kit tasks list-lists`  
**`tasks-create-cli`** — `google-kit tasks create --tasklist <l> --title <t> [--due YYYY-MM-DD]`  
**`tasks-delete-mcp`** — destructive; confirmation required  
**`keep-create-cli`** — `google-kit keep create --title <t> --text <body>` (note BD-6 availability risk)  
**`keep-delete-cli`** — destructive; 403/404 surfaces as Permission/NotFound

### Adding a Capability

**`add-capability`**  
Context: `docs/dev/SERVICE-PATTERN.md`  
Task: Add a new read op `myservice.list`. Walk through files, function signature, registration, doc generation, verification.  
Success: Creates services/myservice/{__init__,models,core}.py; runs docgen_gen; runs pytest + editorial — all without reading source.

### Error Triage (7 classes)

| Task | Error class | Required action |
|------|------------|-----------------|
| `triage-transient` | `Transient` | Retry ≤3 with backoff; escalate if still failing |
| `triage-auth` | `Auth` | Stop; run `google-kit auth login`; no retry |
| `triage-quota` | `QuotaRateLimit` | Wait retry_after (default 60s); retry once; escalate |
| `triage-permission` | `Permission` | Surface to operator; no retry |
| `triage-notfound` | `NotFound` | Surface to operator; no retry |
| `triage-validation` | `Validation` | Fix input; retry once; escalate if still failing |
| `triage-unknown` | `Unknown` | Escalate immediately; no retry |

### Escalation / Deviation

**`escalation-destructive`** — display exact op + target IDs; wait 'yes, proceed'; execute once; record run_id  
**`escalation-deviation`** — trivial/additive = auto-approved; non-trivial = stop and request operator approval

### Observability

**`run-id-audit`** — `run_id` in response `meta` field correlates CLI/MCP calls in audit log
