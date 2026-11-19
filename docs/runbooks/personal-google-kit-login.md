# Enroll one reviewed personal Google Kit profile

`google-kit auth login --personal` is the fresh-profile enrollment route. It
stages the client and exchanged tokens in memory, verifies the reviewed client,
Google account and exact granted scopes, then creates four previously absent
Keychain items. It never updates or deletes an existing item. Profile names,
client JSON and a successful diagnostic do not prove personal ownership or
grant consent; the operator must review that separately before the command.

## Prepare the exact operation

The agent prepares and the host owner reviews the accepted source/runtime,
personal Google Cloud project and installed-app OAuth client, expected account
email/subject, fresh explicit Keychain profile, exact scope list and complete
registry projection digest. Confirm the personal client in the authenticated
Cloud console. Unknown/work ownership remains held. No profile scan, inherited
default, new scope union or source-owner approval supplies destination consent.

The client-secret JSON must be the explicitly reviewed personal desktop-client
file at an absolute path, owned by this account, unshared and readable only by
its owner. Bind its SHA-256 in the review packet. The command follows no path
aliases, refuses changed identity/bytes and never repairs the file. Retaining,
moving or deleting the downloaded secret file requires its own reviewed
handling; the login command leaves it unchanged.

Use the current accepted Google Kit and bootstrap source together. An installed
bootstrap with the same version string but without the qualified create-only
primitive is insufficient; there is no fallback to overwriting `set`. Private
fixture results alone do not qualify the native Keychain or an installed
distribution.

```text
google-kit --profile PERSONAL_NEW_PROFILE auth login --personal \
  --expected-email owner@example.net \
  --expected-subject EXPECTED_GOOGLE_SUBJECT \
  --expected-client-id REVIEWED_CLIENT.apps.googleusercontent.com \
  --expected-project-id reviewed-personal-project \
  --client-secret-file /absolute/private/personal-client.json \
  --client-file-sha256 REVIEWED_FILE_SHA256 \
  --config-dir /absolute/private/google-kit \
  --inventory-sha256 REVIEWED_COMPLETE_REGISTRY_PROJECTION_SHA256 \
  --personal-scope openid \
  --personal-scope https://www.googleapis.com/auth/userinfo.email \
  --personal-scope https://www.googleapis.com/auth/drive.readonly
```

This is a synthetic example, not a recommended or approved scope grant. The
agent builds the complete operation projection using `name`, `scopes`, `posture`
and `flag` for every registry spec and computes
`personal_preflight.inventory_digest`. All 106 operations remain coverage
evidence; this does not make them 106 migration requirements or authorize their
execution. Select the actual scopes through the personal need/owner review.

## Behavior and boundaries

The mode refuses a missing/default profile, any existing credential item,
`--force`, legacy `--scopes` and nonempty `GOOGLE_KIT_EXTRA_SCOPES`. It requests
only the explicit `--personal-scope` values, with an account hint and explicit
consent/account selection. A hint does not authenticate the account. The PKCE
listener binds one ephemeral IPv4 loopback socket, bounds accepted requests and
closes/joins its own listener on success, refusal, timeout or browser failure.
Headless mode prints the authorization URL and still requires the browser to
reach that local listener; it does not use deprecated copy/paste redirects.

Code exchange is one fixed HTTPS POST to Google's token endpoint. Token/account
diagnostics use the accepted fixed token-info route and, only when needed, its
minimal Drive identity fallback. These transports use explicit TLS, no ambient
proxy, redirect or retry, bounded JSON and closed error reasons. No document,
message, event or contact body is requested by enrollment. Returned token scope
metadata must agree exactly with the reviewed scope list before persistence;
partial or additional grants remain held rather than triggering another flow.

The exact client file and explicit authorization snapshot are checked again
after the browser flow and after creation. The mode leaves authorization data
unchanged: absence retains the canonical default-deny meaning. It does not seed
or grant operation permissions, refresh a token, select a global profile,
register MCP, launch services or claim complete provider functionality.

Keychain creation uses the OS duplicate-item refusal with no update flag or
pre-delete. Writes carry a bounded JSON payload on stdin to an isolated Python
helper using Apple's Security framework; secrets never enter process argv. The
helper disables site packages and inherits only the required local session and
locale fields, preserving actual HOME/CODEX_HOME while excluding loader,
Python-path, proxy and SSH-agent injection variables. The
helper preserves long Unicode and multiline UTF-8 values (up to 1 MiB), emits no
passwords or native diagnostics, changes no search list/default and never reads
existing password data. Every proposed item is validated before the first
create. Error stderr with a zero process exit remains a refusal. Existing
regular `SecretStore.set` uses the same transport while retaining its explicit
update semantics; the personal enrollment mode never calls it. The native
helper uses the legacy generic-password API to match the existing default
Keychain contract. Symbol/fixture results do not prove actual Keychain, ACL or
OS behavior; those remain separate native qualification gates.

## Failures and subsequent use

There is no multi-item Keychain transaction here. Items are created in order:
client ID, client secret, refresh token, then access token. Every created item
is read back and preceding values are rechecked. A failure can leave a partial
fresh profile or an uncertain last create. The held JSON result names the
successful/uncertain keys without their values and requests review. No automatic
retry, rollback, deletion or profile reuse occurs; foreign edits are preserved.
Do not interpret a held result as completed login or installation, even if all
four items happen to be present. Any cleanup or retry needs a fresh exact
decision based on the actual remaining state.

Successful enrollment proves only the bounded account/client/scope and
create/readback operation. Follow the separate inspection runbook and complete
actual runtime/functional, native registration, owner admission, retention and
release gates before accepting the full migration connection. Normal legacy
`auth login` remains its existing compatibility route and is not the personal
identity-before-persistence procedure.

The required source job also runs the stdlib-only personal authentication and
storage contract with site packages disabled. The actual package registry/CLI
integration is qualified separately; neither this contract nor metadata checks
cover excluded cross-kit dependencies or native Keychain behavior.
