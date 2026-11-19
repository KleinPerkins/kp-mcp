# Native Google Docs style provider

This route lets an authenticated native Google Docs connector consume canonical
schema-1 Google Kit style data. It qualifies only document-style capture and
application. It does not establish equivalence for Google Kit's other operations,
replace its CLI/MCP identity, register a server, enable a tool, grant OAuth scopes,
change per-profile authorizations, or qualify the existing registrar writer.

## Shared interface

`google-kit/src/google_kit/services/docs/style_profile.py` is a dependency-free
module. Load that exact accepted file through `importlib.util.spec_from_file_location`
when a native host does not have the Google Kit Python package installed. Normal
Google Kit Docs operations import the same planning implementation through their
existing service core. Neither route duplicates the style transformation logic.

- `capture_native_profile(document, document_id=..., tab_id=...)` returns a
  canonical schema-1 profile from a complete native document readback. It does
  not save the profile or overwrite an installed starter.
- `prepare_native_update(document, profile, document_id=..., revision_id=...,
  tab_id=..., mode="definitions" | "normalize")` returns requests, the exact
  target and tab, `write_control.requiredRevisionId`, and SHA-256 bindings for
  the document snapshot, profile and requests. It does not apply the plan.
- Document identity must match. Preparation requires the actual current revision.
  Complete body, named-style and document-style readback is required. Multiple
  tabs, including child tabs, require explicit selection; duplicate/missing tab
  identities, unknown profile/style fields, nonfinite JSON and snapshots above
  1 MiB are refused. Tab traversal is bounded to 64 tabs and eight child levels.
- Both raw Google API tabs (`tabProperties`/`documentTab`) and the current native
  connector's flattened tabs (`tabId`/`body`/`namedStyles`/`documentStyle`) are
  accepted explicitly. A flattened tab's document ID must match when supplied;
  ambiguous mixed shapes are refused. The complete original readback, including
  metadata and native elements outside the style projection, is hash-bound.
- `definitions` updates supplied named/document style definitions. `normalize`
  additionally applies supplied styles to existing top-level body paragraphs,
  using their provider-reported UTF-16 ranges. It preserves the existing Google
  Kit scope: it does not traverse table cells, headers or footers. Neither mode
  inserts/deletes text or replaces native controls. Empty starters prove no
  captured style or successful authoring.

The returned hashes are evidence bindings, not an approval token. A caller must
not treat document data, a matching plan or installed tool names as authorization.
Account identity, scopes, destination ownership and actual successful readback
remain independent host/provider checks.

## Bounded personal destination qualification

Perform this only after normal owner source acceptance at an exact reviewed head
and a verified export of this module. Routine setup authorization may cover this
fixture exercise; an explicit account/OAuth, model, publication, additional-root
or destructive owner gate still requires its actual decision. Never infer those
decisions from this runbook or from JSON input.

1. Record host build, connector/tool discovery, source commit/module hash and the
   actual personal account identity. Refuse a work identity, unavailable identity,
   new consent requirement or insufficient tool schema. Do not copy OAuth tokens,
   Keychain items or another client's configuration. Registration stays unchanged.
2. Use at most one newly created native Google Doc containing synthetic style
   fixtures in at most two tabs. Record the ID from the successful create result;
   never select an existing document by its title. Follow the host's Google Docs
   creation and default-folder workflow. Creation must not be retried on an
   uncertain outcome; reconcile that outcome first.
3. Before content writes, read that exact file's metadata. Verify the personal
   account owns it, it is a native Doc, and it has no non-owner permission or
   shared-drive placement. Verify its actual parent organization through metadata.
   If this fails, stop before adding content; do not repair sharing or mutate
   any existing parent. No shares, invites, comments, messages or calendar writes.
4. Keep the newly created fixture ID and tab identities in a private caller
   receipt. Insert only synthetic heading/body text, including a non-BMP character
   to exercise UTF-16 indexes. Native named heading styles and control types must
   remain intact. Use a readback revision guard for each content/style update.
5. Hash and read the installed generic/placeholder data. Prepare an empty-starter
   plan as a data-consumer check without overwriting it or claiming it is a
   captured style. On the new fixture only, capture and plan a nonempty schema-1
   profile through the accepted interface. Exercise both definition application
   and top-level paragraph normalization; every request must target the recorded
   fixture/tab and carry the actual required revision. A rejected stale revision
   is a refusal check, never permission to drop the guard or blindly retry.
6. Read the changed areas after the planned writes. Compare actual named/document
   styles and paragraph/text ranges with the supplied profile. Verify unchanged
   text, other tabs and native elements. JSON/metadata proves structured styling;
   if claiming visual/page layout, separately export and render the relevant PDF.
   Do not infer rendered appearance from metadata or HTML.
7. Preserve original profiles, configuration, registration and source pins by
   comparing their pre/post hashes and filesystem identities. Store only synthetic
   fixture data and bounded receipts privately. Keep the fixture as private test
   evidence unless its exact cleanup is separately authorized. Never trash or
   permanently delete a target merely because it has the fixture's title.

Report source acceptance, pure-runtime tests, native discovery/identity, local
bootstrap consumption, actual capture/application and any visual result
separately. Failure or missing evidence leaves the corresponding item required.
This exercise cannot close the separate full Google Kit connection requirement.

## Verification

The required `repo.kp-mcp.m3-verify` job invokes the dependency-free contract:

```bash
python3 -B google-kit/tests/test_native_doc_styles.py -v
```

With the normal locked workspace dependencies, also run existing Docs, profile,
recipe and CLI/MCP adapter parity tests. They must keep their prior behavior and
error envelopes. Tests use disposable local state, never a live Google account.

The Google Docs request/range contracts are documented at
[requests](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request)
and [document ranges](https://developers.google.com/workspace/docs/api/reference/rest/v1/documents#Range).
