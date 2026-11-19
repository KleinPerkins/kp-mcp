# Run an explicitly reviewed personal Google Kit consumer

The personal consumer route is selected by the paired global options
`--personal-context` and `--personal-context-sha256`. It covers the existing CLI
operations and `google-kit mcp`, including composite and recipe service factories.
It creates no registration, login, grant or retained installation. Source tests
and a context digest do not prove personal Cloud ownership, human consent,
functional API eligibility, native admission or destination acceptance.

## Prepare the destination operation

Use accepted Google Kit and bootstrap source together in a separately qualified
standalone runtime. The host owner reviews the exact source/runtime, command,
account email and numeric subject, personal Cloud project and installed-app client,
explicit profile, private configuration directory, complete registry digest,
exact scopes, allowed operations, existing authorization-file digest and any
additional public-sharing flag. Confirm the client/project in the authenticated
personal Cloud console. Unknown or work ownership stays held. No profile scan,
legacy default, inherited configuration, source approval or successful diagnostic
supplies destination consent. Follow `personal-google-kit-login.md` for separately
reviewed fresh enrollment; this consumer never enrolls or adopts credentials.

The existing configuration directory must be owned by the invoking account with
mode `0700`. The explicit context is an owned, single-link, regular `0600` file at
an absolute path with no symlinked path components. Its closed JSON shape is:

```json
{
  "schema": "google-kit/personal-runtime-context/v1",
  "profile": "personal-example",
  "expected_email": "owner@example.invalid",
  "expected_subject": "1234567890",
  "expected_client_id": "reviewed-client.apps.googleusercontent.com",
  "expected_project_id": "reviewed-personal-project",
  "config_dir": "/absolute/reviewed/private/config",
  "scopes": ["openid", "email", "https://www.googleapis.com/auth/tasks.readonly"],
  "inventory_sha256": "<exact complete registry projection SHA-256>",
  "allowed_operations": ["tasks.list_lists"],
  "authorization_file_sha256": null,
  "extra_flags": []
}
```

This is a synthetic shape, not an approved operation. Do not copy example
identities, invented digests or placeholder paths into a live enrollment or run.
The full registry remains 106 operations; `allowed_operations` narrows the actual
reviewed invocation authority without removing capabilities from the catalog.
The existing per-profile authorization file remains default-deny for gated
operations. A gated operation needs its persisted `1` and the reviewed exact file
digest. The file must be private; absent grants deny writes. Environment write
overrides are ignored on this route. Public sharing additionally requires the
explicit `GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE` entry in `extra_flags` and the
underlying operation grant. No general write umbrella is accepted there.

`openid` and the email scope are required for verified refresh identity. Only the
documented OIDC `email`/`profile` aliases normalize to their corresponding
`https://www.googleapis.com/auth/userinfo.*` scopes. Duplicate alias equivalents
refuse. All other scopes compare exactly; no union, broad-scope implication or
automatic consent expansion occurs. Functional availability of Workspace-only
APIs, particular resources and per-operation provider permissions stays separate.

## Execute the reviewed consumer

Invoke the exact qualified runtime with both options and the reviewed command.
For example, after a real owner review, a read operation has this command shape:

```text
<qualified-google-kit> --personal-context <absolute-context-file> --personal-context-sha256 <reviewed-sha256> tasks list-lists
```

Use the same paired options with `mcp` for a separately admitted native consumer.
The catalog and local help do not execute provider operations or grant access.
Legacy auth/bootstrap commands are refused with a personal consumer context;
fresh enrollment and native registrar/retention remain separate owner workflows.
An explicit conflicting profile is refused. The context, directory identities,
registry and authorization digest are rechecked at the consumption boundaries.
The personal route never resolves `GOOGLE_KIT_PROFILE`, `CHAOS_LABS_ROOT` or a
default configuration as its account/configuration source.

The first actual service construction refreshes the selected profile in order to
bind a fresh access token to the reviewed account/client. Subsequent SDK refreshes
use the same path. Fixed bounded TLS requests reach only Google's token and X509
certificate endpoints, without proxy, redirect, request logging or automatic
retry. RS256 ID-token signature, issuer, audience, presenter when supplied,
subject, verified email and lifetime are checked before persistence. An `at_hash`
claim is checked against the staged access token when present. Missing or invalid
identity evidence stays held; tokeninfo/Drive diagnostic inspection is not an
application authorization gateway or fallback.

The exact granted scope set must match the review. Under a bounded thread/file
lock, the consumer rereads the selected client and credentials, stages the token
response, rechecks context/grants/credentials, writes a rotated refresh token
first when present, reads it back, then writes and reads back the access token.
No credential value enters argv, journals, error strings or audit records.
Google API resources use packaged static discovery and an explicit non-proxy HTTP
transport, with HTTPS Google API endpoint checks before sending requests and no
redirect following. Ambient SDK credential, quota, universe or mTLS settings are
refused before credential/provider access. Personal audit records use only the
private `personal-audit.jsonl`; ambient audit paths and telemetry exporters are
not used. The invoking process's actual `HOME` and `CODEX_HOME` are preserved.

## Holds and recovery

The consumer creates only its named `.personal-refresh-<profile>.lock`,
`.personal-refresh-<profile>.json`, possible `.personal-stage-<random>` files and
personal audit file beneath the explicit configuration directory. A durable
`pending` journal precedes the token request. `committed` follows verified token
writes. Journals contain only schema, context digest, random attempt ID and state.
The lock must be an owned single-link private empty regular file; an unavailable
or changed lock fails closed. Initial journal publication is exclusive. Updates
compare exact preimages under the cooperative lock. These checks are ordinary
drift protection, not a hostile same-user filesystem CAS guarantee.

A pending, malformed, changed-context or unknown journal holds the profile before
another refresh. Network uncertainty, a response without valid identity, foreign
credential edits, a partial token write or uncertain journal update causes a hold;
the consumer performs no automatic retry, deletion, rollback, journal reset or
namespace reuse. Preserve the journal/staging files and original failure. Obtain
a separately reviewed owner recovery operation before any credential or journal
change or retry. A durable journal cannot make Google's token rotation and four
Keychain items one atomic transaction. Existing-item ACLs, native transport and
the exact installed interpreter require their own destination qualification.

## Source verification boundaries

The offline fixture suite exercises actual signed synthetic tokens, service
construction, all registry authorization/injection shapes, CLI/MCP dispatch,
foreign edits, partial writes, context/path/lock refusals and legacy compatibility.
The required stdlib owner job additionally exercises real context/storage
primitives through `personal_auth_contract.py`; it does not replace the full
package or destination qualification. All real account, OAuth, provider,
registration, retention and release gates remain outside source-fixture results.

Protocol references: [Google OIDC reference](https://developers.google.com/identity/openid-connect/reference),
[Google ID-token verification](https://googleapis.dev/python/google-auth/latest/reference/google.oauth2.id_token.html).
