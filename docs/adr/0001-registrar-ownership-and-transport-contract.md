---
{"approval":{"actor":"KleinPerkins","date":"2026-10-28","review_sha256":"375b173d48b7432a03a5bd5a9eb38baf4d006fec3071245ea7eb5fb09b747c9f"},"authority":"semantic","github_repository_id":1271164179,"id":"ADR-0f31e13a-6afc-503a-97c8-1d6a4e7cbf7f-978cc6ef-0bf6-546e-a498-051f23e8aec8","lifecycle":"approved","mutability":"frozen_after_approval","provenance":[],"relations":[],"repository_key":"0f31e13a-6afc-503a-97c8-1d6a4e7cbf7f","schema":"doc-warden/artifact/v2","supersedes":null,"type":"adr","version":1}
---
# ADR 0001: Registrar ownership and transport contract

Owner: KleinPerkins/kp-mcp. Contract version: 1. Prepared: 2026-10-28.
Canonical lifecycle and acceptance evidence are recorded in doc-warden metadata
and its receipt. Publication or file presence alone does not establish acceptance.

## Decision

Extend `kp-mcp-bootstrap`'s existing `BaseRegistrar`, `CursorRegistrar`,
`CodexRegistrar` and `ClaudeRegistrar` with typed transports, explicit ownership,
field-aware reconciliation and recoverable local transactions. Keep one registrar
writer for each target. Add no service runtime, connection catalog or installer.
The normative specification below is part of this decision, so it freezes with
the ADR rather than becoming a separately editable competing authority.

Retain DECISIONS.md D4: current Google, Snow and Widget kit servers remain stdio
binaries serving all existing clients. Broaden only the registrar's representation
to include separately owned remote Streamable HTTP definitions. Retain B6: no
secret values in host configuration or source definitions. Preserve account,
scope, local enablement, tool policy, approval policy and timeout choices.

Acceptance selects this contract; it does not authorize its implementation,
package release, installation, live registration, sign-in, service operation or
downstream distribution. Those gates remain explicit below.

## Why

At owner main `802f79fa845b05ac0ce0a44a769a83773bd869a4`, `ServerEntry` models
command/args/env only. Each adapter assigns the whole entry at the server name;
the current sibling-preservation tests do not protect fields inside that entry.
`unregister` removes a same-name entry without ownership evidence. Atomic rename
protects against partial file contents but supplies no comparison against a
concurrent writer or durable transaction recovery. These are source findings,
not reports of an observed live user-data loss.

Snow's existing bootstrap supplies caller paths, dry-run output and status,
which are the closest consumer patterns. Its exact full-entry comparison must
eventually become comparison of owned fields so preserved policy does not look
like a registration defect. The registrar must never interpret successful
serialization as enabled, authenticated, discovered or operational.

## Alternatives and consequences

Whole-entry replacement is simpler but loses local policy. Treating Cursor's
installed entry as a shared definition preserves the current competing-source
problem. A new catalog/installer in kp-mcp would duplicate dev's ownership. The
selected extension keeps the existing adapter boundary and adds only the state
needed to prove ownership and safe updates.

The cost is a versioned local receipt/journal and stricter conflict handling.
Unproved legacy entries require an adoption decision. Non-cooperating app file
writers cannot be made transactional by a Python lock; the implementation must
refuse writes without a qualified exclusive-write window or native conditional
write mechanism. Availability may be lower until that boundary is proven.

## 1. Authority and input separation

| Input or state | Authority | Registrar responsibility |
|---|---|---|
| Kit launch contract | Kit owner in kp-mcp | Project the supplied reviewed stdio definition |
| Cross-host connection inventory, selection and migration | dev, INT-014 | Consume a bounded definition; never discover or mutate the catalog |
| Machine paths and approved credential references | Private host overlay | Bind supplied values without copying credentials or reading environment values |
| Enablement, allow/deny, approvals, timeouts, overrides | User/host policy | Preserve their exact semantic values and native precedence |
| OAuth grants, account links, native credential storage | Native client or app | Preserve; do not read stores, refresh, sign in, revoke or change scopes |
| App/plugin-managed connection | App/plugin | Return external ownership; no local duplicate |
| Receipt and interrupted-write journal | kp-mcp registrar | Record observed owned projections and recovery facts only |

The caller supplies `source_owner`, stable `connection_id`, immutable
`source_revision`, `definition_digest`, host/scope and one exact config path.
`connection_id` is distinct from the native server name. A source repository name
or name match alone establishes no target ownership. Resolve supplied target
paths at preview; no recursive config discovery, network calls, shell expansion,
service start or executable probing occurs during planning.

## 2. Typed definition and adapter mapping

The proposed closed `kp-mcp/registration-definition/v1` has these required fields:
`schema`, `connection_id`, `source_owner`, `source_revision`, `native_name`,
`transport`, `owned_paths`. Unknown source fields and unknown schema versions
refuse; unknown host fields are preserved. `definition_digest` is SHA-256 of the
canonical definition bytes and is carried in the request, not self-embedded. `owned_paths` uses RFC 6901
JSON Pointer escaping over this definition (for example `/transport/env/EXAMPLE_PROFILE`);
adapter mappings translate those leaves to host paths without treating dots in
names as nesting. The ownership set must equal the complete supplied source
projection: stdio requires `/transport/kind`, `/transport/command`,
`/transport/args` and one path for every supplied env key; HTTP requires
`/transport/kind` and `/transport/url`. Omitted, extra, ancestor-overlapping or
duplicate ownership claims refuse. Native `type` fields are derived aliases of
the owned discriminator, never an independently claimable source field.

A transport switch removes only incompatible fields proved source-owned by the
previous receipt (stdio command/args/owned env leaves, or HTTP URL/type aliases),
and adds the new complete projection. Any incompatible remaining host/user field
blocks the switch; no native mixed command-plus-URL configuration is emitted.
A new auth-binding decision is required for every switch and endpoint change.
A same-transport update cannot silently erase an owned required field.

`transport` is exactly one of:

- `{"kind":"stdio","command":"/opt/example/bin/example-kit","args":["mcp"],"env":{"EXAMPLE_PROFILE":"default"}}`.
  `command` is a nonempty absolute executable path supplied by the caller;
  `args` is an explicit list of strings (including a valid empty list); `env` is
  an explicit string map of declared non-secret configuration values. No shell
  evaluation, inherited environment harvesting or HTTP fields.
- `{"kind":"streamable-http","url":"https://mcp.example.invalid/mcp"}`.
  Require an absolute HTTPS URL without userinfo, fragment or query. Preserve its
  supplied path exactly. No command/args/env, SSE fallback, stdio bridge, custom
  executable auth helper or implicit transport negotiation. An endpoint that
  requires another shape returns unsupported and needs a later bounded contract.

`owned_paths` contains exact leaf paths into source launch fields, never wildcards
or whole host maps. `args` is one ordered value; `env` ownership is per key. The
transport discriminator is source-owned and maps to adapter-specific fields.
The registrar validates the claimed paths against the closed field matrix below.

| Adapter | stdio projection | Streamable HTTP projection candidate |
|---|---|---|
| Cursor | `mcpServers[name]`: command, args, declared env leaves; retain baseline omission of explicit type until the qualified adapter requires it | `mcpServers[name].url`; native header-reference syntax only from private auth binding |
| Codex | `mcp_servers[name]`: command, args, declared env leaves | `mcp_servers[name].url`; native env reference fields from private auth binding |
| Claude | User-scope `mcpServers[name]`: `type=stdio`, command, args, declared env leaves | User-scope `type=http`, url; preserve project-scoped entries separately |

These mappings follow the official [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp),
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference),
[Cursor MCP documentation](https://prod.cursor.com/docs/mcp) and
[Claude MCP documentation](https://code.claude.com/docs/en/mcp), read 2026-10-28.
They are design inputs, not qualification of an installed build. Each adapter
must bind its supported mapping revision and observed host/surface/build. An
unknown host version yields unverified support; a required unsupported field
refuses the entire target operation without silently dropping it. Preserve
existing Claude stdio behavior; new Claude remote support may remain explicitly
unsupported until qualified. INT-015 owns native connection qualification.

## 3. Field and nested-map ownership

| Field class | Ownership and merge rule |
|---|---|
| Transport, command, ordered args, remote URL | Source-owned after creation/adoption. Three-way comparison against last recorded projection; transport/URL changes additionally require a fresh host/auth binding review |
| Declared non-secret `env[key]` | Individual source-owned leaves. Remove only previously owned leaves intentionally removed from the definition; retain every other key |
| Host launch overrides (`cwd`, `envFile`, extra `env_vars`, remote placement) | Host-owned and preserved. If their effective behavior conflicts with the proposed launch contract, return a conflict; do not edit or ignore it |
| Enablement, allow/deny, tool approvals, timeout and retry controls | User/host-owned, including nested per-tool maps. Preserve absence as absence, false as false and list order. No copying from another host |
| Native auth references and nested `headers`, `env_http_headers`, `auth`, `oauth` maps | Host/auth-owned. Retain every unrelated leaf. A separately approved reference-only host binding may own an exact credential-reference leaf; portable source never owns these maps |
| Unknown fields and unmanaged siblings | User/unmanaged-owned. Preserve semantic values and native scope; no inferred ownership, deletion or normalization |

Header names compare case-insensitively for collision detection while retaining
their original spelling. Multiple case variants with different values are an
unresolved conflict. A new desired env/header leaf colliding with an unowned leaf
is a conflict even if equal, until explicit adoption covers that leaf. A source
deletion does not authorize deletion of a user-added sibling. Never deep-merge
lists element-by-element or treat missing/empty/null values as interchangeable.

For an owned leaf, let B be the last recorded postimage, C the current value and
D the desired value, including an explicit absent sentinel. If C=B, apply D;
if C=D, retain it; otherwise report owned-field drift and write nothing. If both
source and host changed the leaf differently, no last-writer-wins rule applies.
Resolve drift through an exact new preview and bounded owner choice; never `force`.

A preserved setting can defeat the requested contract. For example, an unknown
write-enabling Snow environment override cannot be reported read-only merely
because args still contain `--read-only`. The kit supplies its invariant
validator. Preserve the override and return policy conflict; do not remove it,
enable writes, or weaken service-specific approval rules.

## 4. Creation, adoption, withdrawal and external ownership

Creation requires an absent target name, no receipt for a different identity,
and caller-supplied inventory evidence that this is not a duplicate app-managed
connection. Unknown app ownership blocks an asserted managed creation; it does
not trigger service discovery. One source identity may have several native host
projections, each separately receipted.

For an existing entry, adoption requires either a valid registrar receipt or an
explicit migration evidence record approved for this exact preview. Migration
evidence binds owner/connection identity, host/scope/name/path, current whole-file
digest, exact proposed owned leaves and their digests, source revision, evidence
provenance and the retiring writer's handoff. Equal bytes or executable names
alone are insufficient. Conflicting owner claims remain unresolved. Adoption
of equal bytes may create a receipt without changing the config; report that
state mutation separately from a config change.

INT-014 controls the old dev mirror's retirement and catalog. The new registrar
requires evidence that the former writer has stopped before applying to adopted
entries; it does not disable that writer itself. Absence of a receipt after an
interruption or manual deletion does not authorize re-adoption or deletion.

Unregister requires proof of the entire entry's ownership and matching owned
projection. If any user, host or unknown fields remain, removal would erase
their choices: return `removal_conflict` with no config/ownership change. Do not
leave a broken partial entry, silently forget ownership or remove the enclosing
server map. A whole-entry removal needs its separately reviewed exact consequence
and is outside the ordinary safe unregister path. Missing entry is a no-op;
retiring an extant matching receipt is a separate explicitly shown state action.

## 5. Private auth references

`AuthBinding/v1` is host-local, not part of the portable definition. Closed kinds
are `none`, `native-oauth` and `environment-reference`. It binds a host/scope,
opaque approved account reference, target origin/path digest, unchanged grant
reference and exact allowed native reference fields. `native-oauth` preserves
the client's grant/config and never initiates authorization. An environment
reference contains a variable name, not its value; missing values are left for
separate native qualification. A reference is not proof of authentication.

For qualified Codex mappings, use `bearer_token_env_var` or per-header
`env_http_headers`; Cursor uses its documented interpolation syntax. Claude
reference syntax must be explicitly qualified before use. Static secret headers,
literal credentials in URLs/args/env, embedded client secrets and fallback
credentials are rejected. Existing native auth settings are preserved without
printing their contents. Do not broaden scopes, switch accounts/resources,
generate helper commands, read Keychain/token stores or rewrite authentication
precedence. A URL/origin or transport change cannot reuse old auth authority
implicitly; require a new target-bound decision or report `auth_binding_conflict`.

Existing config is not claimed secret-free. A literal or unclassified auth
credential inside the selected entry blocks that entry's entire mutation with
`existing_auth_material`; leave bytes untouched and request separately authorized
native remediation. Never delete or export it. A secret in an unrelated sibling
remains privately preserved; it must never appear in previews, result values,
logs or Git. This distinction preserves B6 without inventing permission to clean
existing credentials. Known reference syntax is classified by the pinned adapter;
unknown auth shapes fail closed, not by an assumed complete secret regex.

Receipts have distinct `source_projection` and `auth_projection` ownership maps,
each with its issuing owner, approved binding digest, leaf paths and last
postimage digests. Source updates cannot claim, remove or adopt an auth leaf.
Adding/changing/removing such a leaf requires exact AuthBinding approval and a
prepared action explicitly naming it. Existing native-OAuth fields remain
host-owned and unmodified. Endpoint or transport change invalidates prior auth
binding before any config write, including when source and auth use the same
physical field map.

Non-secret classification is a caller responsibility backed by a closed allowed
field/value policy and tests. Pattern matching alone is not secret detection.
Preview/results/logs use identifiers and digests, never unrestricted host values.
Whole-file recovery material, which can already contain secrets, remains only in
the private local storage described next.

## 6. Durable state and transaction boundary

Use a caller-overridable private state directory, defaulting to
`${XDG_STATE_HOME:-~/.local/state}/kp-mcp/registrars/v1/`. Require an absolute
directory with current-user ownership, mode 0700 and no symlinked components;
files are regular mode 0600. Reject unsupported special files and multiply linked
writable targets. Reject a state directory inside any Git working tree, including a caller override
or one reached through a path alias. No state lives in Git, capability metadata, native config
extension keys or dev's connection catalog. State is not a security boundary
against the same OS user and is never AWA identity/registration evidence.

Key receipts by canonical config target plus host/scope and connection identity;
serialize the entire config file under one lock, across server names and path
aliases. The receipt stores schema/adapter version, source identity/revision/
digest, native-name/host/scope binding, owned leaf paths and last projection
digests, target identity, operation id and verified postimage. It is evidence of
past application, not a desired-state catalog. Unknown state versions or corrupt
receipts block mutation; never downgrade or replace them opportunistically.
Receipts and journals distinguish absent from present-empty, include each target
pre/postimage digest and mode, and link the previous successful receipt digest.
A journal also records `prepared|config_replaced|verified|committed` as a hint;
recovery trusts observed matching bytes over the last persisted phase marker.

Each operation covers exactly one config file and its corresponding registrar
state. Multiple hosts are a sequential batch with per-target results; there is
no all-host atomicity claim. Preflight the full batch before beginning; after an
unexpected failure, stop unstarted targets and expose the exact partial outcome.

Use a write-ahead journal: lock/recheck; persist/fsync private preimage, projected
postimage and pending journal; atomically replace config using a same-directory
temporary file; fsync parent; re-read/parse/hash; atomically persist/fsync ownership
receipt and completed journal. Durable write ordering and permission preservation
must be tested. Refuse a target whose ACL/metadata cannot be preserved. A backup
failure writes nothing. Retain incomplete journals until resolved. Retain the
latest successful rollback material per target; older material may be pruned
only after verified successor completion, leaving non-secret operation digests.

Current symlink support is retained only for an explicit, stable leaf link:
bind the logical path, link text, resolved regular target and each ancestor's
identity in preview; recheck before writing and on verification. Preserve the
link, replace only the resolved target and lock by that target. Reject dangling,
cyclic, retargeted or symlinked-directory paths. This stricter policy is a visible
compatibility change from unconditional `realpath` following, not a silent fix.

Atomic rename plus a registrar lock cannot exclude an app/editor that ignores
the lock. Apply requires a qualified caller-controlled exclusive-write window
covering config and state, or a host API with true conditional replacement.
Recheck target identity/bytes immediately before replace and after it; detected
divergence halts. Checks are drift detection, not an atomic compare-and-swap
guarantee. No qualified exclusivity means `concurrency_unqualified`, no write;
the registrar does not stop apps or services to obtain exclusivity. INT-014 must
qualify the writer handoff before any live adoption.

### Writer-window qualification

`WriterWindow/v1` requires `schema`, qualification id/digest, issuer owner,
issuer source revision, mechanism, host/surface/build, mapping digest, canonical
config/state target identities, acquisition reference, acquired-at, expires-at
and release method. Maximum lifetime is the prepared operation's 10 minutes.
A hash of caller prose is insufficient: the adapter must recognize the exact
qualification id/digest from its reviewed versioned mechanism table and validate
scope, freshness and live acquisition before every config/state mutation.

Closed mechanisms are `fixture-isolation`, `native-conditional-write`, and
`native-exclusive-window`. The first is valid only for an explicitly disposable
fixture root with no host discovery exposure. The latter two require an actual
supported host API/contract, provider-issued acquisition evidence, and tested
acquire/conditional-write-or-hold/release semantics in that adapter's reviewed
qualification entry. Registrar locks, file mtime/hash checks, stale PID claims,
caller booleans or retirement of the old dev mirror do not qualify them.

At this decision baseline only fixture isolation is qualified. All live mutations
for Cursor, Codex and Claude return `concurrency_unqualified` until the owner
accepts a concrete native mechanism with evidence in a successor qualification
entry. No fictitious host endpoint is specified. INT-014 owns resolving that
live prerequisite, or escalating its explicit unmet requirement; it cannot claim
migration completion while it is missing. The registrar neither stops apps nor
creates a new admission/security framework. Release of a native window follows
its qualified mechanism on success/failure; failure to release is reported.

## 7. Preview, apply, recovery and rollback result contracts

Use closed versioned records. Canonical digest encoding is UTF-8 JSON with sorted
keys, compact separators and one trailing newline; reject duplicate keys and
non-finite numbers. Config pre/postimage digests cover exact file bytes. For decimal-valued host settings, preserve their native parsed/lexical form
inside config bytes; records bind those bytes by digest, never convert settings
to a lossy numeric representation. Keep
arbitrary preserved host data out of record serialization. Reject unknown fields
and incompatible versions in records consumed for a write.

`Preview/v1` (`schema=kp-mcp/registrar-preview/v1`) requires: operation UUID,
action enum (`register|adopt|unregister|recover|rollback|cancel`), definition digest,
source owner/revision/connection id, adapter version and mapping digest, host/
surface/build/scope, logical and resolved target binding, target/config/receipt/
journal preimages (digest or absent), desired postimages, sorted owned leaf
actions, preserved-path list, conflicts, private recovery reference, auth-binding
digest or not-applicable, writer-window evidence digest, expiry and preview_digest.
The preview digest covers every preview field except itself; this immutable
preview has no prepared-payload or final action digest, avoiding a circular hash.
Preparation produces the final approval-bound action digest as specified below. Private local preview bytes
contain enough exact projected output to apply; shareable output contains only
the bounded, redacted leaf summary and digest. Preview never creates backups,
locks, receipts or target directories; explicit saving of its private operation
record is a separately reported local write.

`prepare` validates a pure Preview and explicitly saves a mode-0600
`PreparedOperation/v1` under the private state root. Its closed fields are schema,
operation id, action, full preview, exact config postimage bytes, exact next
source/auth ownership snapshot bytes, preimage/absence bindings, mapping/definition/auth/
writer qualification digests, approval audience, expires-at and payload digest.
Ownership snapshots bind operation id and config postimage, but do not embed
their own digest or final action digest. A separate terminal operation receipt
records those computed digests. The payload digest excludes itself; the action digest binds that payload digest
and the redacted preview summary. Encoded bytes remain private, never in a
shareable preview. Target expiry is fixed before preparing, never extended by
saving again. The returned `PrepareResult/v1` reports prepared-record id/digest and final action digest,
state_changed, expiry and config_changed=false. Re-saving identical bytes is a
no-op; a UUID collision with different bytes refuses. No backup is created yet.

The approval audience is the exact source owner, connection id, host/scope,
canonical target and action. `Approval/v1` binds that audience, operation id,
action digest, prepared payload digest, issuer authority/reference, issued-at,
expires-at and choice=apply. The caller's existing owner workflow validates the
human/operation authority and supplies the envelope through an adapter-owned
validation function; unrecognized issuer, wrong audience, missing explicit choice,
stale receipt or reusable boolean refuses. This is operation hygiene within one
OS-user trust boundary, not cryptographic proof or a new authorization service.
Fixture approval evidence is accepted only inside fixture-isolation and cannot
satisfy live scope. No generic consent permits service writes.

Apply loads the exact prepared record and checks payload, audience and approval
before locking/rechecking. It writes its stored postimages; it never recomputes
new desired bytes from current inputs. Any requested amendment needs a new
operation. Cancellation of a saved but unapplied prepared record is an explicit
`cancel` action with exact record digest/approval and a retained non-secret
cancellation receipt; it deletes private staged output only after proving no
config/ownership mutation began. Ambiguous partial operations require recovery.

`ApplyRequest/v1` requires the exact prepared record id/payload digest,
operation id, action digest and operation-
bound approval evidence from the calling owner workflow. Approval authorizes only
the reviewed config/state delta, never service execution. Maximum preview life is
10 minutes. Missing prepared bytes return `prepared_record_required`. A changed source, host mapping, auth reference, target, link, receipt,
journal or writer-window condition requires a new preview and approval. Exact
already-completed retry returns the recorded receipt; changed-input replay refuses.

All operation results use `schema=kp-mcp/registrar-result/v1` with required fields:
`operation_id`, `action_digest`, `action`, `outcome`, `config_changed`,
`state_changed`, `verified_postimage` (digest, verified absent sentinel, or null for unverified), `receipt_id` (or null),
`recovery_id` (or null), `reason_codes`, `conflicts`, `next_action` and
`observations`. `outcome` is one of `ready`, `applied`, `no_change`, `conflict`,
`unsupported`, `failed`, `recovery_required`, `recovered`, `rolled_back`, `cancelled`.
`applied` requires durable receipt plus parsed and re-read verified postimage;
failure after config replacement is `recovery_required`, never plain success.
`reason_codes` is a closed enum with at least malformed_config, unsupported_schema,
unsupported_transport, unsupported_field, ownership_unknown, owner_conflict,
owned_field_drift, policy_conflict, removal_conflict, auth_binding_conflict,
preimage_changed, target_changed, concurrency_unqualified, permission_denied,
backup_failed, write_failed, verification_failed, journal_invalid, context_required,
recovery_conflict, stale_preview, prepared_record_required, approval_invalid,
existing_auth_material and writer_release_failed. Do not serialize raw exception strings.

Recovery is explicit and offline, with `RecoveryRequest/v1` containing original
prepared id/digest, new operation id, observed config/receipt/journal digests,
`disposition=complete|cancel`, context and exact approval. Recovery itself has a
new prepared record and action digest. Let C0/R0 be original config and ownership
preimages; C1/R1 their exact planned postimages; P a valid pending journal and T a
valid committed journal. For receipt-only adoption C0=C1, so the receipt is the
decisive changed value. The closed transition table applies to register, adoption,
unregister, receipt retirement and rollback restoration alike:

| Observation | complete | cancel |
|---|---|---|
| C0/R0/P, including receipt-only operations | Recheck all original approvals, source/auth/writer conditions and finish exact C1 then R1 | Retain C0/R0; mark cancelled, state_changed=true; remove unused private staging only after terminal receipt is durable |
| C1/R0/P | Revalidate C1; finish R1 and terminal receipt, config_changed=false | Refuse recovery cancel; a separately approved rollback is required |
| C1/R1/P | Verify both; finish T, state_changed=true | Refuse cancel; offer separately approved rollback |
| C1/R1/T | Return prior committed result, config_changed=false, state_changed=false | Refuse cancel; offer separately approved rollback |
| C0/R1, any third value, missing/invalid journal or mismatched receipt | recovery_conflict, write nothing | recovery_conflict, write nothing |
| Retained valid cancelled marker with C0/R0 | Refuse completion/replay of cancelled operation | Return prior cancellation, both changed flags false |

Evaluate receipt-only equal-C cases using R before the C0/C1 rows. If R0=R1 too,
no target mutation was needed; any saved preparation can only be explicitly
cancelled or completed as a no-change terminal record. State-only recovery never
claims runtime success. Phase markers are hints, not authority; current bytes
must match. Keep incomplete journals and required rollback material until a
verified terminal transition. Do not prune divergent or unresolved material.

`operation_ref` is a closed tagged reference to either a committed receipt or a
pending journal; never a filename guessed from recency. Interrupted-operation
rollback is permitted for valid C1/R0/P or C1/R1/P. Its new prepared operation and
approval bind the original prepared payload, journal and current config/ownership
pair exactly. Restore C0/R0 under the same writer/exclusivity and durable-write
rules. Persist the inverse journal with an explicit original-operation link
before any reverse write; while that inverse is pending, forward completion or
replay of the original refuses. If the inverse is interrupted, recover that
inverse with the same transition table. On verified restoration, record its
terminal receipt and terminalize the original as rolled_back; never replay the
original as applied. Divergence of either config or ownership remains a conflict.
This path does not require the missing original successful receipt.

Committed-operation rollback also has a new preview/approval. Require current whole-file and ownership
state to match the saved successful postimages, then restore prior bytes or
remove a file created by the operation if still exactly matching, and restore
the prior receipt state through its own journal. Later edits anywhere in that
file block whole-file rollback; a fresh reconciled inverse operation may preserve
them but is not called exact rollback. Divergent data is never overwritten.

`observations` has separate registered/enabled/authenticated/tools_discovered/
safe_read entries, each carrying `pass|fail|unknown|not_applicable|disabled`,
timestamp, host/surface/build, connection revision and bounded evidence reference.
Registrar success sets only registered based on config verification. It leaves
all runtime states unknown unless a distinct qualified observer supplied them;
an auth-free definition alone does not prove a live read. No blanket operational
boolean, auth refresh, tool invocation or health-check network access is added.
Operator `next_action` must say what remains unresolved in plain language.

## 8. Compatibility and coordinated release

Preserve import paths and `SERVER_NAME` subclass usage. Keep legacy
`ServerEntry(command, args=None, env=None)` as a stdio compatibility constructor,
including its observed 0.2.0 behavior that both omitted and empty args become
`["mcp"]`; only the new typed constructor treats explicit `[]` as empty. Do not
reinterpret legacy `as_dict()` as a host-policy ownership grant.

The future API keeps these existing registrar classes and adds keyword-only
`RegistrationContext/v1`: source owner, stable connection id, source revision,
definition digest, host/surface/build/scope, mapping version, state directory,
auth-binding id/digest and writer-window reference. Kit factories supply their
stable identity; callers do not infer it from `SERVER_NAME`. Cross-host inventory
selection remains dev-owned. All context and record schemas reject extra fields.

The adapter API is `preview(path, definition, *, context) -> Preview`,
`prepare(preview) -> PreparedOperation`, `apply(prepared, approval) -> Result`,
`recover(prepared, disposition, approval) -> Result`,
`rollback(operation_ref, *, context) -> Preview`, and
`inspect_registration(path, *, context) -> Inspection`. Preparation is local
state persistence only; it never writes host config. Apply operates on exact
prepared bytes, with the guards below. No second registrar or catalog is added.

Legacy `register(path, entry, *, context=None, prepared=None, approval=None)`
and `unregister(path, *, context=None, prepared=None, approval=None)` preserve bool
success semantics: True means config changed, False means a determinate no config
change. They never manufacture approval, prepare/apply implicitly, or turn a
conflict into False. The 0.3 behavior matrix is normative:

| Observed state | No context | Valid matching context |
|---|---|---|
| Absent entry, register | context_required | Change requires prepared operation + exact approval |
| Equal entry with receipt | context_required: identity cannot be inferred | False only after ownership and source/auth/state consistency checks; runtime status remains unknown |
| Equal entry without receipt | context_required | ownership_unknown; explicit adoption required |
| Existing drift/conflicting owner | context_required | Typed drift/owner conflict; no write |
| Missing entry, unregister | False for absence only; no receipt/state action | False if no state cleanup; any receipt retirement requires exact prepared approval |
| Existing entry, unregister | context_required | Safe whole-entry removal requires proven ownership, no preserved leaves, prepared operation + approval; otherwise removal_conflict |

`would_register` requires context for every call. It returns bool only for a safe,
determinate preview; unresolved ownership/policy raises. `Inspection/v1` contains
only present, ownership status, owned-projection-match, reason codes and the five
separate observation states. It returns no values from host entries. Deprecate
raw `current_entry`; in 0.3 it requires context and returns the bounded Inspection
shape, never raw native fields. This deliberate return-shape break is included in
the coordinated consumer release. No consumer may use it for full-entry equality.
Typed exceptions derive from `BootstrapError` and contain only reason codes and
bounded target/operation identifiers, never raw config or exception messages.

This is a documented behavior-breaking release, proposed `kp-mcp-bootstrap`
0.3.0, with versioned Python/result/state contracts. Existing 0.2.0 deployments
remain unchanged until their consumer explicitly upgrades. Google, Snow and
Widget currently exact-pin 0.2.0; all affected consumer calls, package version/
exports, exact dependency pins, generated wheel metadata and `uv.lock` must move
in one reviewed release slice. Include template/example/documentation consumers
found at implementation preflight. Tag/version every consumer package whose public bootstrap/status behavior changes,
including Google, Snow and Widget; validate produced wheel dependency metadata
and immutable release refs. No silent dependency range widening. Older
adapters must not act on v1-owned targets; INT-014's handoff prevents mixed writers.
No version, pin, lockfile or consumer change is authorized in this decision task.

## 9. Future acceptance cases and execution gates

These are required future implementation tests, not results claimed by this ADR.
Use disposable paths and synthetic values; no live auth, config or service writes.

| Cases | Required proof | Integration coverage |
|---|---|---|
| REG-01–04 | Typed union rejection; exact stdio regression; remote projection or explicit unsupported; quoted/dotted names and format parse/round-trip with comments preserved by a syntax-aware TOML editor; JSON retains all semantic data and exposes any formatting delta | CFG-01, MCP-02 |
| OWN-01–06 | Same-name unknown/equal/conflicting adoption; app-managed collision; one-writer handoff; per-key env/header merge, casing collisions and removed owned leaves; disabled/approval/timeout/unknown fields survive; safe unregister refusal | MCP-01, CFG-01, AUTH-01 |
| TXN-01–08 | Idempotent retry with no new backup; changed source/preimage/receipt refusal; two connection names sharing a config serialize; app-writer exclusivity failure; stable/retargeted/dangling symlinks; injected failure before and after every durable step; permission/ACL preservation; correct partial batch results | CFG-01, ROL-01 |
| REC-01–04 | Unapplied/postimage-only/complete/divergent recovery cases; rollback after clean apply versus later user edit; originally absent target; corrupt/missing journal/receipt and unknown state version | ROL-01 |
| API-01–04 / SEC-01–03 | Legacy constructor/imports/bool/errors; all exact-pinned consumer dry-run/status/registration paths; read-only invariant conflict; synthetic secrets in host siblings never enter output or Git; malformed input refuses without backup; states do not overclaim runtime success | AUTH-01, EVD-01, MCP-02 |

The following named assertions are mandatory, beyond the grouped cases above:

- PTR-01: reject partial, noncanonical, escaped-incorrectly, duplicate and overlapping ownership pointers; test stdio→HTTP and HTTP→stdio against the union of prior/new leaves and incompatible preserved policy.
- PREP-01: apply exact saved postimages; refuse missing/changed prepared bytes, wrong payload/action digest, issuer/audience/choice, expiry and altered-input replay; prepared cancel cannot affect config or committed state.
- WRITER-01: a second native writer ignoring a registrar lock cannot pass a fabricated qualification digest; every unqualified live mutation refuses; test cross-process/path-alias/server-name races and window expiry/release failure.
- AUTH-02: selected-entry literal/unknown auth blocks without disclosure or deletion; unrelated sibling secret remains private; wrong-origin/transport binding and source claims on auth-owned leaves refuse.
- REC-05: exercise every recovery table row under complete and cancel, receipt-only adoption, originally absent config, interrupted-operation rollback from both C1/R0/P and
C1/R1/P (including interrupted inverse and blocked original replay), committed
rollback receipt restoration and zero-change preparation; assert exact files and both changed flags.
- API-05: exercise every public legacy method against the context matrix, redact all Inspection/exception outputs, and verify every changed consumer package's version/tag/pin/wheel metadata.
- STATE-01: refuse wrong-owner/mode state, symlinks, hardlinks, Git-contained state, malformed/unknown records and unpreservable target metadata; no backup/config change on refusal.
- GOV-02: distinguish prerequisite previews from actual acceptance; prove merged ADR plus required event/receipt under explicitly authorized protected-path delivery. File presence or ordinary App readiness alone cannot pass.

Implementation should reuse existing registrar tests and Snow bootstrap seams,
adding tests for these substantive missing behaviors. Do not call live doctor,
auth or service-write smoke tests. Select current owner offline checks at execution
preflight; at this baseline the PR recipe's required repository check is
`bash .github/scripts/verify-capabilities.sh`. Full package/consumer regression is
required for the eventual behavior-breaking release, beyond today's docs checks.

G0: Owner accepts this exact ADR through a supported doc-warden operation and
normal repository delivery verifies the merge. No inferred approval from dev
ADR0012 or a prepared preview. Canonical authoring is currently blocked by the
missing v2 profile and legacy empty index shape. Profile adoption, mutable-index
normalization and semantic ADR acceptance are distinct operation-bound previews;
approving one does not approve the others. A conditional fixture rendering is
not an applicable owner acceptance preview.

Every such operation writes governance event/receipt files below `_ops`. The
current owner PR policy marks `_ops` protected. Delivery must obtain the actual
repository-prescribed owner/admin authorization for those exact protected
changes; ordinary reviewer-App auto-merge eligibility must not be presumed.
No manual merge exception, auto-merge manipulation or protection change is
granted here. If that route is unavailable, report delivery incomplete and
keep implementation blocked even if the document bytes have been accepted.

G1: A separately assigned INT-013 implementation task derives its exact file/test
slice from this contract and current owner instructions. This decision-preparation
task cannot start it. Routine technical review/checks remain the agent's duty.

G2: Implemented registrar and coordinated release slice pass fixture contracts,
consumer regressions and normal reviewer-App delivery. Source merge is not install.

G3: INT-014 accepts dev's catalog/mirror-retirement and migration/handoff evidence;
only then may an authorized live target operation be previewed and approved.

G4: INT-015 performs separately bounded native auth/discovery/read qualification
with unchanged accounts/scopes. Broader activation and downstream distribution
retain their integration/orchestrator gates.

## 10. Authority pointers and exclusions

Integration authority: dev accepted ADR0012 and accepted PRD/SPEC/PLAN for
repository key `54aec621-9236-53d2-87b7-9a60ef4ec92e`, as present at
`14fa5f95fe86178f32e966cb747ab9c884f4b92b`. The SPEC's DEC-07 and section 7,
PLAN's INT-013–015 and validation appendix define this owner boundary. Frozen
records, workloads and sidecars stay unchanged. This ADR owns the component
contract; dev remains the catalog and host-installer owner.

Prerequisite delivery references: [dev PR376](https://github.com/KleinPerkins/dev/pull/376),
[skills PR240](https://github.com/KleinPerkins/skills/pull/240),
[dev PR377](https://github.com/KleinPerkins/dev/pull/377) and retained activation
evidence [dev PR379](https://github.com/KleinPerkins/dev/pull/379). Their temporary
bootstrap exceptions have expired; PR379's one-PR merge exception grants no merge
authority here.

No changes to oauth.py, secrets.py, live config, installers, services, protected
automation, AWA source/ADR0026, mcp-builder, memory or excluded repositories.
No fabrication of identity from cwd/PID/attachment. No direct downstream edits.

