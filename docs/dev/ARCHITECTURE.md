# google-kit architecture (expansion track)

Backbone adopted from the architecture brief (§1 planes, §2 router/manifest,
§8 observability envelope) for the E0–E6 expansion-and-hardening track. This
layer is ADDITIVE: the OpSpec registry stays the single source of truth, the
41 legacy 1:1 ops are untouched, and the router serves only new thick-read /
composition capabilities.

## Plane / seam model (§1)

Google split Workspace along a structural seam. Route per-verb across planes,
never one-tool-per-API. An OpSpec declares its plane via `OpSpec.plane`.

| Plane | APIs | Owns |
|-------|------|------|
| container | Drive v3 | identity, discovery, bytes in/out, permissions, copy, trash, change feed |
| content | Docs, Sheets, Slides, Forms | per-artifact semantic model + atomic `batchUpdate` |
| history | Drive Activity v2 | consolidated, read-only who/what/when |
| eventing | Workspace Events + per-API `watch()` | change subscriptions (coverage is uneven) |
| identity | People (+ Admin SDK Directory, deferred) | profiles, directory/org graph, aliases |
| automation | Apps Script | server-side JS escape hatch only |
| messaging | Gmail | mail read/search/compose/modify |

A real unit of work is usually a composition (`container ⊕ content ⊕ (history|eventing|identity)`),
not a single API — see the §4 recipes (E3).

## Capability router + manifest (§2)

A **capability** is an artifact-neutral unit of exposure (`doc.read`,
`file.share`, `history.read`). An **adapter** is a concrete `(api, method)`
binding behind a capability.

### Manifest

The registry IS the manifest. `core/manifest.py` reads it as data: groups ops
by `capability` and `plane`, parses each op's ordered `adapters`
(`id, api, method, selector, scopes, cost_hint, fallback_on`), and builds the
alias/keyword index for the E6 helper. Both surfaces (MCP tools, CLI verbs)
are still generated from this one source, so they cannot drift.

### Router

`core/router.py` resolves `(capability, context) → Plan` deterministically.
It is PURE — it selects an adapter, an ordered fallback chain
(Chain-of-Responsibility), or a recipe; it does not call Google. Adapter
execution and LIFO saga compensation live in the service/recipe layer
(E1/E3). This is how the kit is **thick on reads/composition** while writes
stay **thin/explicit** (mutations remain 1:1 and auditable).

### Selector language

Each adapter's `selector` is a structured, deterministic predicate:

- `{}` or `{"any": True}` — always matches (default / catch-all).
- `{"k": v, ...}` — AND: every key must equal `context[k]`.
- `{"any_of": [pred, ...]}` — OR: at least one sub-predicate matches.

The router scope-gates adapters: an adapter is eligible only if its required
scopes are a subset of the caller's granted scopes (when a scope set is given).

## Observability envelope (§8)

`core/normalize.py:Meta` carries the envelope on every invocation:
`{run_id, op, latency_ms, api, method, scopes_used, calls, quota_units_est,
fallback_used, recipe_id, saga_compensated}`. Base fields are populated by
every op; routing/composition fields are populated by router/recipe
capabilities via `build_meta(...)`. Legacy ops leave the extended fields at
their (safe) defaults.

## Least-privilege scope manifest (§8)

`core/scopes.py:SCOPE_MODES` encodes the per-mode least-privilege scope sets
(read_ingest default; create_edit; broad_authoring; gmail_write flagged;
advanced admin/automation). The *currently consented* live set remains
`core/auth.py:GOOGLE_KIT_SCOPES` — new modes are declared here but require
operator scope approval + sandbox consent before joining the live flow.

## Additive boundary (E0)

E0 ships the model + router + manifest accessors + scope manifest + envelope
fields as scaffolding, proven by unit tests against synthetic specs. Real
capabilities populate `capability`/`plane`/`adapters`/`aliases` and wire the
router as they are built in E1–E6.
