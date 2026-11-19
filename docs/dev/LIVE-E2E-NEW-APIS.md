# Live e2e: NEW APIs + WATCH/subscription ops (operator runbook)

Companion to [`SANDBOX.md`](./SANDBOX.md). The cutover-minimum and existing-scope
live suites (`google-kit/tests/test_sandbox_e2e.py`,
`test_sandbox_e2e_e1.py`) already pass. This runbook covers the **deferred**
surfaces in `google-kit/tests/test_sandbox_e2e_new_apis.py`, which need operator
action beyond the already-consented cutover scopes:

1. **NEW APIs** — People, Drive Activity, Apps Script, Workspace Events.
   People / Drive Activity / Apps Script require **new OAuth scopes** to be
   consented on the sandbox profile (they are *declared* in `core/scopes.py` but
   *not granted* in the live consent union `core/auth.py:GOOGLE_KIT_SCOPES`).
   **Workspace Events needs no new scope** — its `events.*` ops authorize via the
   already-consented `drive.readonly` — but the *Google Workspace Events API* must
   still be enabled (Library) and a Pub/Sub topic provisioned (§2).
2. **WATCH / subscription ops** — these need a push destination:
   - **Pub/Sub-delivered**: `gmail.watch`, `forms.watches`, `events.subscribe`.
   - **HTTPS-webhook-delivered**: `drive.changes_watch`, `calendar.watch`.

Without the prerequisites below, the whole suite **skips cleanly** (no creds, no
failures). Each prerequisite unlocks a specific slice.

---

## 0. Op ↔ scope ↔ prerequisite matrix

| Op | API | Posture | OAuth scope(s) | New consent? | Push destination |
|----|-----|---------|----------------|:---:|------------------|
| `people.get` | People v1 | read | `directory.readonly` + `contacts.readonly` + `userinfo.profile` | **yes** | — (³) |
| `people.batch_get` | People v1 | read | `directory.readonly` + `contacts.readonly` | **yes** | — |
| `people.connections` | People v1 | read | `contacts.readonly` | **yes** | — |
| `people.search_directory` | People v1 | read | `directory.readonly` | **yes** | — (Workspace-only) |
| `people.list_directory` | People v1 | read | `directory.readonly` | **yes** | — (Workspace-only) |
| `drive_activity.query` | Drive Activity v2 | read | `drive.activity.readonly` | **yes** | — |
| `script.create` | Apps Script v1 | write | `script.projects` | **yes** | — |
| `script.get_content` | Apps Script v1 | read | `script.projects.readonly` | **yes** | — |
| `script.update_content` | Apps Script v1 | write | `script.projects` | **yes** | — |
| `script.deployments` | Apps Script v1 | read | `script.projects.readonly` + `script.deployments.readonly` | **yes** | — |
| `script.versions` | Apps Script v1 | read | `script.projects.readonly` | **yes** | — |
| `script.metrics` | Apps Script v1 | read | `script.metrics` (⁴) | **yes** | — |
| `script.run` | Apps Script v1 | write | `script.projects` + `script.external_request` | **yes** | — (SKIPPED — needs API-executable deployment) |
| `events.subscribe` | Workspace Events v1 | write | `drive.readonly` | no² | Pub/Sub |
| `events.list` | Workspace Events v1 | read | `drive.readonly` | no² | — |
| `events.patch` | Workspace Events v1 | write | `drive.readonly` | no² | — |
| `events.delete` | Workspace Events v1 | destructive | `drive.readonly` | no² | — |
| `gmail.watch` | Gmail v1 | write | `gmail.readonly` | no¹ | **Pub/Sub** |
| `forms.watches` | Forms v1 | write | `forms.body.readonly` + `forms.responses.readonly` | no¹ | **Pub/Sub** |
| `drive.changes_watch` | Drive v3 | write | `drive.readonly` | no¹ | **HTTPS webhook** |
| `calendar.watch` | Calendar v3 | write | `calendar` | no¹ | **HTTPS webhook** |

¹ The four watch ops use scopes **already in the live consent union**
(`gmail.readonly`, `drive.readonly`, `calendar`, and `forms.body.readonly` which
is subsumed by the consented read-write `forms.body`). They need **no
re-consent** — only a push destination (Pub/Sub topic or verified webhook).

² Workspace Events `subscriptions.{create,list,patch,delete}` authorize using the
**target resource's** scope — there is **no dedicated Workspace Events scope**
(Google Cloud Console rejects a fabricated one as `invalid_scope`). The
kit's `events.*` ops target Drive, so they authorize via `drive.readonly`, already
in the live consent union — **no re-consent**. `events.subscribe` still needs the
*Google Workspace Events API* enabled (Library) and a **Pub/Sub** topic (§2). Drive
event types are CloudEvents-formatted `google.workspace.drive.file.v3.ACTION`
(valid file actions: `created`, `moved`, `contentChanged`, `deleted`, `trashed`,
`untrashed`, `renamed` — there is **no** `updated`; the version is **v3**, not
`v1` — see [Subscribe to Google Drive events](https://developers.google.com/workspace/events/guides/events-drive)).
A consumer `gmail.com` account **can** create a **single-file** subscription with
a **file-scoped** event (`contentChanged`) — verified live, so
`test_events_subscription_lifecycle` **passes** the full subscribe → list → patch
→ delete lifecycle. (The earlier `created`-on-a-single-file shape was a
request-shape bug: `created` is a *container* event — "a file added to a folder
or shared drive" — so it needs a folder/shared-drive target, not a file, and
Google rejected it with `EVENT_TYPE_CONFIG_MISMATCH`.) The `_skip_if_workspace_only`
guard remains a safety net: shared-drive targets (shared drives are
Workspace-only) and org-restricted accounts can still 400/403 on the
Workspace-domain signal (same family as Keep / BD-6), in which case the test skips
cleanly — but it never masks a request-shape/validation error.

³ `people.get('people/me')` reads the authenticated user's **own profile** (the
PROFILE source). `directory.readonly` (domain) and `contacts.readonly` (contacts)
do **not** authorize the self-profile, so reading `names`/`emailAddresses` for
`people/me` needs the **profile** scope (`userinfo.profile`) — confirmed by the
live 403 *"Request requires one of the following scopes: [profile]"*. This is an
**additional per-login operator consent** (§1), requested via
`GOOGLE_KIT_EXTRA_SCOPES` / `--scopes`; it is **not** added to the shared grant
`GOOGLE_KIT_SCOPES`. `people.batch_get` does **not** need it — `getBatchGet`
returns a `200` envelope with per-entry status (so it never hard-403s), which is
why the same self-read passes for batch_get but not for the singular get.

⁴ `script.metrics` (`projects.getMetrics`) authorizes **only** via the dedicated
`https://www.googleapis.com/auth/script.metrics` scope — `script.projects` and
`script.projects.readonly` do **not** cover it (confirmed by the live 403
*ACCESS_TOKEN_SCOPE_INSUFFICIENT* for `MetricsService.GetMetrics`). It is one of
the new-API per-login scopes (§1a/§1c), declared in the `advanced` manifest mode;
**not** added to the shared grant `GOOGLE_KIT_SCOPES`. (Earlier the kit mis-declared
this op's scope as `script.projects.readonly`; corrected to `script.metrics`.)

---

## 1. New OAuth scopes — add to the consent screen + re-consent

### 1a. Exact scope strings to add

Add these to the sandbox OAuth client's consent screen (Google Cloud Console →
*APIs & Services* → *OAuth consent screen* → *Data access* → *Add or remove
scopes*). Also enable each API under *APIs & Services* → *Library*:

```
# People API  (enable: People API)
https://www.googleapis.com/auth/directory.readonly
https://www.googleapis.com/auth/contacts.readonly
https://www.googleapis.com/auth/userinfo.profile   # people.get self-read (people/me); see ³

# Drive Activity API  (enable: Drive Activity API)
https://www.googleapis.com/auth/drive.activity.readonly

# Apps Script API  (enable: Apps Script API)
https://www.googleapis.com/auth/script.projects
https://www.googleapis.com/auth/script.projects.readonly
https://www.googleapis.com/auth/script.deployments.readonly
https://www.googleapis.com/auth/script.external_request
https://www.googleapis.com/auth/script.metrics   # script.metrics getMetrics; see ⁴
```

> **Workspace Events** is intentionally absent: it has **no dedicated OAuth scope**.
> Its `events.*` ops authorize via the already-consented `drive.readonly`. Still
> enable the *Google Workspace Events API* under *APIs & Services → Library* and
> provision a Pub/Sub topic (§2) — but add **no new scope** to the consent screen.

> These **nine** strings are exactly the scopes used by the new-API OpSpecs that
> are **absent** from `core/auth.py:GOOGLE_KIT_SCOPES`. They are declared in the
> per-mode manifest (`core/scopes.py`: `read_ingest` carries the People +
> Drive Activity scopes plus `userinfo.profile` for the `people.get` self-read (³);
> `advanced` carries the Apps Script scopes — the read-write `script.projects` /
> `script.deployments` there subsume the `.readonly` variants the read ops
> declare, but `script.metrics` (⁴) is a **distinct** scope that nothing subsumes,
> so it is listed explicitly). The `events` mode is just `drive.readonly` (already
> granted), so Workspace Events adds **no** new scope. Neither the manifest nor
> `GOOGLE_KIT_SCOPES` changes: these nine scopes are requested **per-login** for
> the sandbox profile only (§1b/§1c), not added to the shared consent union.

### 1b. How login requests scopes (do NOT edit `GOOGLE_KIT_SCOPES`)

`GOOGLE_KIT_SCOPES` (the single shared consent union in `core/auth.py`) is left
**unchanged**. Adding these scopes there would expand the grant for *every*
profile and force a re-consent for all existing users — a cutover-consent
regression.

`google-kit auth login` requests **exactly `GOOGLE_KIT_SCOPES` (the 10 cutover
scopes) by default**, and OAuth only ever grants the scopes the app
**requests**. So adding the nine new scopes to the consent screen (§1a) is
necessary but **not sufficient**: a plain `google-kit auth login` still requests
only the 10, and the new scopes never land on the token no matter what the
consent screen offers.

To grant the new scopes to the **sandbox profile only**, request them explicitly
for that one login via the opt-in `--scopes` flag or the
`GOOGLE_KIT_EXTRA_SCOPES` env var. Both take a comma/space-separated list of full
Google scope URLs and are unioned with `GOOGLE_KIT_SCOPES` for that single login
(deduplicated; the base 10 keep their order, the new scopes are appended in
sorted order). Malformed scopes fail loud. This does **not** touch the shared
union, so no other profile (prod included) is affected.

### 1c. Re-consent the sandbox profile with the new scopes

Run a forced login that requests the union of `GOOGLE_KIT_SCOPES` + the nine new
scopes. `--force` re-consents even though a token already exists:

```bash
GOOGLE_KIT_EXTRA_SCOPES="https://www.googleapis.com/auth/directory.readonly,https://www.googleapis.com/auth/contacts.readonly,https://www.googleapis.com/auth/userinfo.profile,https://www.googleapis.com/auth/drive.activity.readonly,https://www.googleapis.com/auth/script.projects,https://www.googleapis.com/auth/script.projects.readonly,https://www.googleapis.com/auth/script.deployments.readonly,https://www.googleapis.com/auth/script.external_request,https://www.googleapis.com/auth/script.metrics" \
  uv run google-kit auth login --profile sandbox --force
```

Equivalently, pass the same scopes with the repeatable `--scopes` flag instead of
the env var (each value may be comma/space separated):

```bash
uv run google-kit auth login --profile sandbox --force \
  --scopes "https://www.googleapis.com/auth/directory.readonly https://www.googleapis.com/auth/contacts.readonly https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/drive.activity.readonly" \
  --scopes "https://www.googleapis.com/auth/script.projects https://www.googleapis.com/auth/script.projects.readonly https://www.googleapis.com/auth/script.deployments.readonly https://www.googleapis.com/auth/script.external_request https://www.googleapis.com/auth/script.metrics"
```

> The `userinfo.profile` scope is the **additional operator consent** required
> only by `people.get`'s `people/me` self-read (³); `script.metrics` (⁴) is the
> one required only by `script.metrics` (`projects.getMetrics`). Both are extra
> per-login scopes like the others here — **not** a change to `GOOGLE_KIT_SCOPES`.

If the consent screen does not re-prompt for the new scopes, revoke first (Google
account → Security → Third-party access → remove the app), then re-run the
command above.

After login, confirm the granted token carries the new scopes before running the
new-API slice.

> **Production note:** the same per-login mechanism is how you would grant these
> APIs to a production profile **only if/when prod actually needs them** — again
> without editing `GOOGLE_KIT_SCOPES`. The extras are scoped to a single login,
> not a change to the shared union.

---

## 2. Pub/Sub topic for the Pub/Sub-delivered watches

`gmail.watch`, `forms.watches`, and `events.subscribe` publish to a Cloud Pub/Sub
topic. Create **one** topic in the **same Google Cloud project** as the sandbox
OAuth client, then grant each relevant Google push service account
`roles/pubsub.publisher` on it.

```bash
export PROJECT_ID=<your-sandbox-cloud-project>
export TOPIC_ID=google-kit-sandbox-watch

# 1. Create the topic (a default pull subscription is fine; push delivery to your
#    own consumer is optional — the e2e only asserts the watch resource exists).
gcloud pubsub topics create "$TOPIC_ID" --project="$PROJECT_ID"

# 2. Grant publish rights to each Google push service account you will exercise:

# Gmail push (gmail.watch)
gcloud pubsub topics add-iam-policy-binding "$TOPIC_ID" --project="$PROJECT_ID" \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# Forms push (forms.watches)
gcloud pubsub topics add-iam-policy-binding "$TOPIC_ID" --project="$PROJECT_ID" \
  --member="serviceAccount:forms-notifications@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"

# Workspace Events — Drive target (events.subscribe)
gcloud pubsub topics add-iam-policy-binding "$TOPIC_ID" --project="$PROJECT_ID" \
  --member="serviceAccount:drive-api-event-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

Then point the suite at the fully-qualified topic name:

```bash
export GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC="projects/$PROJECT_ID/topics/$TOPIC_ID"
```

Notes / gotchas:

- The topic **must be owned by the calling project** — Gmail/Forms reject a topic
  from another project.
- Do **not** grant `allUsers` / `allAuthenticatedUsers` — that makes the topic
  public. Only the named `*@system.gserviceaccount.com` accounts.
- Org *domain-restricted sharing* policy can block granting to `system.gserviceaccount.com`;
  add a policy exception for those accounts if the bind fails.
- `events.subscribe` on a **single-file** Drive target with a **file-scoped**
  event (e.g. `contentChanged`) works on a consumer `gmail.com` account (verified
  live). **Container** events (`created`/`moved`) need a folder or shared-drive
  target; shared drives are Workspace-only, so those skip cleanly on a consumer
  account via `_skip_if_workspace_only` (which never masks a validation error).

---

## 3. HTTPS webhook for the webhook-delivered watches

`drive.changes_watch` and `calendar.watch` deliver to an **HTTPS webhook**
(a Drive/Calendar push *channel*), **not** Pub/Sub. Google requires the receiving
domain to be **verified**:

1. Stand up (or reuse) an HTTPS endpoint that returns `200` to Google's
   `POST` (any always-200 receiver works; the e2e only asserts the channel is
   created and then stops it).
2. Verify the domain in [Google Search Console](https://search.google.com/search-console)
   and add it under *APIs & Services* → *Domain verification* in the Cloud
   Console (the project that owns the OAuth client). Push channels to an
   unverified domain are rejected.
3. Point the suite at the endpoint:

```bash
export GOOGLE_KIT_SANDBOX_WEBHOOK_URL="https://<your-verified-domain>/google-kit/push"
```

Teardown calls `channels().stop()` on the created channel, so no long-lived push
channel is left behind.

---

## 4. Run the suite

| Env var | Purpose | Unlocks |
|---------|---------|---------|
| `GOOGLE_KIT_SANDBOX=1` | base creds gate (existing) | nothing alone — required by every test |
| `GOOGLE_KIT_SANDBOX_PROFILE=sandbox` | Keychain profile (existing) | — |
| `GOOGLE_KIT_SANDBOX_NEW_SCOPES=1` | set after §1 re-consent | People, Drive Activity, Apps Script |
| `GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC=projects/<p>/topics/<t>` | §2 topic | `gmail.watch`, `forms.watches`, `events.subscribe` |
| `GOOGLE_KIT_SANDBOX_WEBHOOK_URL=https://<verified>/<path>` | §3 endpoint | `drive.changes_watch`, `calendar.watch` |

Full new-API + watch matrix:

```bash
GOOGLE_KIT_SANDBOX=1 GOOGLE_KIT_SANDBOX_PROFILE=sandbox \
GOOGLE_KIT_SANDBOX_NEW_SCOPES=1 \
GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC="projects/$PROJECT_ID/topics/$TOPIC_ID" \
GOOGLE_KIT_SANDBOX_WEBHOOK_URL="https://<verified-domain>/google-kit/push" \
  uv run pytest google-kit/tests/test_sandbox_e2e_new_apis.py -v -rs
```

Run a single slice (the others skip cleanly):

```bash
# New-API reads only (no push destination needed)
GOOGLE_KIT_SANDBOX=1 GOOGLE_KIT_SANDBOX_NEW_SCOPES=1 \
  uv run pytest google-kit/tests/test_sandbox_e2e_new_apis.py -v -rs \
  -k "people or drive_activity or script"

# Pub/Sub watches only
GOOGLE_KIT_SANDBOX=1 GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC="projects/$PROJECT_ID/topics/$TOPIC_ID" \
  uv run pytest google-kit/tests/test_sandbox_e2e_new_apis.py -v -rs \
  -k "gmail_watch or forms_watches"

# Webhook watches only
GOOGLE_KIT_SANDBOX=1 GOOGLE_KIT_SANDBOX_WEBHOOK_URL="https://<verified>/push" \
  uv run pytest google-kit/tests/test_sandbox_e2e_new_apis.py -v -rs \
  -k "changes_watch or calendar_watch"
```

---

## 5. Expected runtime + teardown guarantees

- **Runtime**: ~30–90 s for the full matrix (14 tests; mostly single round-trips).
  Apps Script `create`/`updateContent` are the slowest (~5–10 s each). No polling
  loops; nothing waits on a notification to actually arrive.
- **Teardown** (identical discipline to the sibling suites — delete in `finally`,
  then `emit_audit`):
  - People / Drive Activity reads create at most one throwaway Doc, deleted via
    raw `files().delete`.
  - Apps Script: `script.create` makes a standalone project (a Drive file);
    cleanup is **best-effort** `files().delete` — Apps Script v1 has no
    `projects.delete`. **Confirm no orphaned `e2e-new-*` script projects remain**
    (greppable by the `e2e-new` run-id prefix in Drive).
  - `events.subscribe`: the subscription is resolved via `events.list` and torn
    down with `events.delete`; the target Doc is deleted.
  - `gmail.watch`: stopped with `users().stop()` (stops all push for the sandbox
    mailbox — safe in the sandbox).
  - `forms.watches`: watch deleted via raw `forms().watches().delete`, then the
    form is deleted.
  - `drive.changes_watch` / `calendar.watch`: channel stopped via
    `channels().stop()`.
- All artifacts are named with the `e2e-new` run-id prefix, so any straggler is
  greppable in the account's Drive/Forms views (see `SANDBOX.md` → Teardown).

---

## 6. What the operator must provide (checklist)

- [ ] Sandbox Cloud project with the four new APIs **enabled**.
- [ ] The **nine new scopes** (§1a) added to the sandbox OAuth consent screen
      (incl. `userinfo.profile` for `people.get`'s self-read (³) and
      `script.metrics` for `script.metrics`'s `getMetrics` (⁴); Workspace Events
      adds none — it authorizes via the already-held `drive.readonly`).
- [ ] Sandbox profile **re-consented with the nine new scopes requested
      explicitly** (`GOOGLE_KIT_EXTRA_SCOPES="…" uv run google-kit auth login
      --profile sandbox --force`, §1c), then `GOOGLE_KIT_SANDBOX_NEW_SCOPES=1`.
- [ ] A **Pub/Sub topic** in that project with `roles/pubsub.publisher` granted to
      `gmail-api-push@`, `forms-notifications@`, and `drive-api-event-push@`
      `system.gserviceaccount.com`; `GOOGLE_KIT_SANDBOX_PUBSUB_TOPIC` set.
- [ ] An **HTTPS endpoint on a verified domain**; `GOOGLE_KIT_SANDBOX_WEBHOOK_URL` set.
- [ ] (For `people.*directory`, and `events.subscribe` on a **shared-drive /
      container** target) a **Google Workspace** account — consumer `gmail.com`
      skips those cleanly. A **single-file** `contentChanged` subscription works
      on a consumer account (verified live).
- [ ] `script.run` stays SKIPPED unless a separate API-executable deployment is
      provisioned in the same Cloud project as the OAuth client.
