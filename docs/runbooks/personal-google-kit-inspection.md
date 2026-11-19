# Inspect one personal Google Kit profile

`google-kit auth inspect` reports the selected token's account and scopes and
the selected profile's persisted write grants. It never grants execution,
refreshes a token, repairs data, signs in, registers MCP or proves installation.
Source acceptance alone does not authorize inspection of a real profile.

## Before a real inspection

The host owner must identify a personal profile and independently review its
OAuth client and expected Google account. A profile name, matching stored
client ID or an app-managed connector identity does not prove client ownership.
Prepare the exact source/runtime identity, selected Keychain namespace, explicit
config directory, expected email and Google subject, reviewed client ID and
complete operation-inventory digest. Preserve existing files and credentials.
Unknown/work ownership holds the operation. Do not discover credentials by
scanning other profiles or importing another client's configuration.

Use the separately qualified standalone Google Kit command. This example uses
synthetic placeholders; the agent prepares real paths and the review packet:

```text
google-kit --profile PERSONAL_PROFILE auth inspect \
  --config-dir /absolute/personal/google-kit \
  --expected-email owner@example.net \
  --expected-subject EXPECTED_GOOGLE_SUBJECT \
  --expected-client-id REVIEWED_CLIENT.apps.googleusercontent.com \
  --inventory-sha256 REVIEWED_OPERATION_PROJECTION_SHA256
```

Build the projection from every current registry spec's `name`, `scopes`,
`posture` and `flag`, and use
`google_kit.core.personal_preflight.inventory_digest` in the qualified runtime.
The command checks that digest before credential access; it does not accept a
filtered selection as the current registry. Preparing the projection is agent
work, with no sign-in or service call required.

## Reads and outputs

The command traverses only the explicit authorization path without following
aliases. It refuses shared, unsafe, oversized, corrupt or changed files. It
reads the selected store's `client_id` first and compares it to the independently
reviewed value before reading `access_token`. It never reads `client_secret` or
`refresh_token` and never changes the store.

Google's fixed diagnostic token-info resource receives the access token over
HTTPS. Audience, presenter, subject, expiry and returned scopes are checked.
If verified email is unavailable, one minimal Drive `about.get` identity read
is permitted only after the expected subject/client match and an appropriate
observed Drive scope. No document, message, contact or event contents are read.
The transport follows no redirects, uses no ambient proxy and makes no retry.
The authorization snapshot must still match after those diagnostics.

JSON output includes the expected identity, a digest of the reviewed client ID,
observed token scopes, all operation scope comparisons and the authorization
snapshot. It contains no token, client secret, refresh token, raw provider body
or client ID. `--format text` reports a compact diagnostic summary.

| Authorization state | Meaning |
|---|---|
| `valid` | The selected canonical schema was read; persisted grants and missing entries are distinguished. |
| `absent_profile` | The selected file was absent; no persisted grant is observed. |
| `absent_authorizations_dir` | The explicit directory had no authorization directory. Nothing is created. |
| `absent_config_dir` | The explicit config path was absent. Nothing is created. |

Unrecorded grants have the canonical default-deny meaning. Environment overrides
are not evaluated. Even an observed persisted `1` is not this command's consent
to execute an operation. Scope comparisons are exact literal comparisons;
broader-scope implications and API/account eligibility require separate review.
The operation inventory is coverage evidence, not permission to run every
endpoint or a new set of migration obligations.

Failures return a closed reason on stderr with a nonzero exit. Missing expected
bindings, mismatching client/account, expired or near-expiry tokens, unreadable
state and detectable changes remain held. Do not retry by granting scopes,
refreshing credentials, repairing files or changing to a different profile.

## Separate decisions remain separate

Personal OAuth setup and token adoption require their own reviewed client,
scope consent and identity-before-persistence procedure. Stock `auth login`
still persists its exchange result before this inspection and is not that
procedure. Keep source acceptance, actual account evidence, functional
qualification, live mutation consent and retained/native registration distinct.
The shared registrar's caller, ownership, writer-exclusion and recovery gates
remain applicable; this diagnostic grants none of their authority.
