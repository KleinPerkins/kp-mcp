# Release Process

Per-package versioning and publish flow for the kp-mcp workspace.

---

## Versioning scheme

All packages follow **SemVer** (`MAJOR.MINOR.PATCH`). Initial version: `0.1.0` for all packages.

| Package | Current version | pyproject.toml |
|---------|----------------|----------------|
| `kp-mcp-bootstrap` | 0.4.0 | `kp-mcp-bootstrap/pyproject.toml` |
| `kp-mcp-testkit` | 0.1.0 | `kp-mcp-testkit/pyproject.toml` |
| `google-kit` | 0.3.0 | `google-kit/pyproject.toml` |
| `snow-kit` | 0.4.0 | `snow-kit/pyproject.toml` |
| `widget-kit` | 0.3.0 | `widget-kit/pyproject.toml` |

Versions are set independently per package — kits may advance faster than the shared engines, and vice versa.

---

## Changelog

Release notes per tag or explicitly unreleased source version. Newest first.

- kp-mcp-bootstrap v0.4.0 / google-kit v0.3.0 / snow-kit v0.4.0 /
  widget-kit v0.3.0 (unreleased source versions, 2026-11-01) — Adds explicit
  maintenance v2 records and a constructor-injected dev validator, preserving
  the strict/v1 path and exact public inspection/preview signatures. Every
  maintenance mutation revalidates current authority and expected images;
  durable reload, child recovery and inverse operations retain mode provenance.
  Consumers and scaffold pin bootstrap 0.4.0. The production caller allowlist is
  empty pending the actual reviewed D2 adapter revision. Source tests and wheel
  builds are not release, installation, live observation or migration evidence.

- kp-mcp-bootstrap v0.3.0 / google-kit v0.2.0 / snow-kit v0.3.0 /
  widget-kit v0.2.0 (unreleased source versions, 2026-10-28) — Adds typed
  registrar definitions, owned-field reconciliation and explicitly approved
  local transactions. Registration needs context, saved prepared bytes and
  approval; equal unreceipted entries need adoption. Inspection is redacted.
  All consumers and the scaffold pin bootstrap 0.3.0. Google registration no
  longer repairs style profiles. Snow setup/repair refuse before profile writes
  when registration authority is missing. TOMLKit 0.15.2 preserves native TOML
  syntax. Only disposable fixtures qualify for writes; live targets remain
  `concurrency_unqualified`. This source change creates no release tags,
  installation, native qualification or runtime/authentication evidence.

- kp-mcp-bootstrap v0.2.0 / google-kit v0.1.2 / snow-kit v0.2.0 /
  widget-kit v0.1.1 (unreleased source versions, 2026-07-10) — Adds a shared
  deterministic intent/workflow engine; preserves Google E6 output; ships
  Snow plain-English CLI/MCP help, context-first workflow recommendations,
  live discovery cues, generated intent docs, and coordinated dependency pins.
- snow-kit v0.1.1 (2026-07-09) — Accepts the standard snow-kit data envelope
  during live doctor safe-read validation; v0.1.0 incorrectly required a
  nonexistent top-level `status` field.
- snow-kit v0.1.0 (2026-07-09) — **First formal snow-kit release.** Adds a
  strict operator-local profile, fail-closed `mcp --read-only`, three-client
  registration lifecycle, offline/live doctor, staging/install verbs, and
  hermetic security regressions.
- v0.1.1 (2026-06-19) — **MCP tool-name sanitization (Cursor compat).** google-kit's MCP tool surface was rejected by Cursor because tool names contained dots (`calendar.create`), violating Cursor's `^[a-zA-Z0-9_]+$` tool-name convention. Adds a shared `mcp_tool_name()` sanitizer (`.`→`_`) in `kp-mcp-bootstrap` (`kp_mcp_bootstrap/docgen.py`), an explicit `{sanitized_name: spec}` round-trip map + collision guard in google-kit's MCP server, and regression tests; regenerated docs/schemas. Bumps **both** `kp-mcp-bootstrap` and `google-kit` to 0.1.1 and advances google-kit's wheel pin to `Requires-Dist: kp-mcp-bootstrap==0.1.1`.

---

## Pre-release checklist

Before tagging any release:

```bash
# 1. Sync and test
uv sync
uv run pytest -q       # must be 0 failed
```

Pass/skip counts grow as ops and tests are added; record the current output, but
the gate is **zero failures**, not a frozen count. Credentialed live-e2e tests
clean-skip offline.

```bash
# 2. Lint the same auto-discovered paths as CI
uv run python -m kp_mcp_testkit.editorial \
  $(uv run python tools/ci_discover.py lint-paths)

# 3. Determinism: every generator is double-run → zero git diff
for pass in 1 2; do
  for kit in $(uv run python tools/ci_discover.py kits | \
    uv run python -c 'import json, sys; print(*json.load(sys.stdin))'); do
    uv run python tools/ci_discover.py regen --kit "$kit"
  done
  uv run python tools/ci_discover.py regen-catalog
done
git diff --exit-code \
  google-kit/docs/ snow-kit/docs/ widget-kit/docs/ \
  docs/CATALOG.md docs/ECOSYSTEM.md

# 4. Build all workspace packages
uv build --all-packages --out-dir dist/

# 5. Doc-loop gate (requires live credentials)
# Run: uv run python -m kp_mcp_testkit.doc_runner docs/dev/doc_task_suite.json
# Record results in docs/DOC-LOOP-REPORT.md before tagging.
```

---

## Bumping a version

Edit the `version` field in the relevant `pyproject.toml`:

```toml
[project]
version = "0.2.0"   # was 0.1.0
```

Also update `__version__` in the package `__init__.py` if it is defined there (e.g. `google_kit/__init__.py`).

Commit the bump before tagging:

```bash
git add <package>/pyproject.toml
git commit -m "bump <package> to <version>"
git tag <package>-v<version>          # e.g. google-kit-v0.2.0
git push origin <tag>
```

---

## Tagging

Tags are cut **only after** all release commits have landed on `main` and the
pre-release checklist is green at that exact HEAD. Tag name = `<package>-v<version>`.

```bash
git switch main && git pull --ff-only
# verify the checklist above is green at HEAD, then:
git tag kp-mcp-bootstrap-v0.1.0
git tag google-kit-v0.1.0
git push origin kp-mcp-bootstrap-v0.1.0 google-kit-v0.1.0   # never --force
```

A tag is immutable once pushed. To correct a mistake, cut a new patch version and
tag that — never move a published tag.

### Tags cut so far

| Tag | Package | Notes |
|-----|---------|-------|
| `kp-mcp-bootstrap-v0.1.0` | kp-mcp-bootstrap | first tag; shared engine |
| `google-kit-v0.1.0` | google-kit | first tag; reference kit #1 |
| `kp-mcp-bootstrap-v0.1.1` | kp-mcp-bootstrap | MCP tool-name sanitization (`mcp_tool_name()`) |
| `google-kit-v0.1.1` | google-kit | MCP tool-name sanitization (Cursor `^[a-zA-Z0-9_]+$` compat) |
| `snow-kit-v0.1.0` | snow-kit | first formal release; generic read-only MCP lifecycle |
| `snow-kit-v0.1.1` | snow-kit | live doctor data-envelope compatibility fix |

---

## Building packages

```bash
uv build --all-packages --out-dir dist/
```

Artifacts land in `dist/` (gitignored). Each member produces a `.tar.gz` (sdist)
and a `.whl` (wheel). Built wheels record **versioned inter-package deps** — e.g.
current `google-kit` source metadata carries
`Requires-Dist: kp-mcp-bootstrap==0.4.0`. The
`[tool.uv.sources] workspace = true` overrides are uv-only and are NOT written
into wheel metadata, so the published artifact is index/git-resolvable.

---

## R13 — installable-whole, three modes

R13 requires the suite to install as a whole **and** each child to install
standalone. There are three delivery modes; the first two need no package index:

| Mode | Mechanism | Index needed? | Status |
|------|-----------|---------------|--------|
| Dev / CI | virtual workspace root + `uv sync` | No | DONE |
| Delivery (current) | immutable **git-pin** of each member to a tag ref | No | DONE |
| `pip install` from an index | private PyPI / Artifact Registry | **Yes** | DEFERRED → second/new consumer |

**Delivery (git-pin) — the current production model.** Because each kit wheel
requires its matching `kp-mcp-bootstrap` version and there is no index hosting
that sibling, a consumer pins **both** members to compatible git tag refs (same
repo, two `#subdirectory=` pins). A clean install then resolves the sibling from
git, not from an index. Validate both tag references in a disposable environment before updating an authorized consumer.

A bare `pip install google-kit` (single package, expecting the sibling from an
index) is **fundamentally index-dependent** and will fail to resolve the matching
`kp-mcp-bootstrap` version until an index exists. That is by design, not a
defect.

### Index graduation trigger (second/new consumer)

> **Successor source guidance:** see [source boundary](../source-successor.md) and the `google-kit-index-graduation` Cursor rule. The original private consumer playbook is omitted. No original delivery state or publishing authorization transfers to this successor.

Stand up a private index when **any** of these is true:

- a second or new consumer needs Google-kit or the kp-mcp suite without matching
  git-subdirectory pins;
- an external/non-git consumer needs `pip install google-kit`;
- the metapackage `kp-mcp` must be `pip install`-able as a whole.

Index options: a hosted private PyPI (Gemfury, Cloudsmith), **Google Artifact
Registry** Python repos, or a self-hosted index. **GitHub Packages cannot host
Python** — it supports npm, Maven/Gradle, NuGet, RubyGems, and Docker/OCI images
only, so it is not an option for these wheels.

When the index exists, set the publish env (`UV_PUBLISH_TOKEN` or
`UV_PUBLISH_USERNAME`/`UV_PUBLISH_PASSWORD`) in CI secrets, and enable the release
job (below). Never commit credentials.

---

## Publishing (dry-run only until an index exists)

`uv publish` is wired but **disabled/dry** in CI (the `release` job runs on tag
pushes, builds, and stops at a dry validation). Validate metadata locally with:

```bash
uv publish --dry-run dist/google_kit-*.whl
```

When an index exists, enable upload with:

```bash
uv publish --index <name> dist/*            # uses [[tool.uv.index]] + UV_PUBLISH_TOKEN
```

---

## Dependency order

Publish in this order when releasing shared engines alongside a kit:

1. `kp-mcp-bootstrap` (no kit deps)
2. `kp-mcp-testkit` (no kit deps)
3. `google-kit`, `snow-kit`, and `widget-kit` (depend on `kp-mcp-bootstrap`)

---

## Adding a new kit to the release flow

The CI `determinism`, `build`, and editorial-lint steps **auto-discover** kits
(`tools/ci_discover.py`), so no CI hand-editing is needed. To release a new kit:

1. Scaffold it from [`template/`](../../template/) (it ships versioned sibling deps).
2. Run `uv run python tools/catalog_gen.py` to refresh [docs/CATALOG.md](../CATALOG.md).
3. Cut and push its `<domain>-kit-v<version>` tag once green on `main`.
