## Continual-learning memory

Machine-mined preferences and workspace facts for this workspace now live in
`agent-learnings.md` (machine-local, git-ignored, never committed). Agents load it as
ancestor context when present; this file holds only hand-authored, human-curated guidance.


<!-- doc-warden:begin -->
## Documentation governance

This repo's documentation structure is governed by `doc-warden`.

| Artifact type | Location |
|---|---|
| Plans | `docs/plans/` — index at `docs/plans/README.md` |
| ADRs | `docs/adr/` — index at `docs/adr/README.md` |
| Runbooks | `docs/runbooks/` |
| Glossary | `docs/GLOSSARY.md` (created when genuine terminology ambiguity arises) |

**Policy:** `~/dev/_ops/doc-warden/POLICY.md`
**Engine:** `~/dev/_ops/bin/doc-warden.sh check kp-mcp` (read-only health check)
<!-- doc-warden:end -->

## Clean successor delivery

This is the source-only `KleinPerkins/kp-mcp` (immutable ID1460922143). Original private Git history and discovery/migration evidence are excluded and preserved separately. Runtime package names and versions are unchanged; no old tag is recreated here. Run `.venv/bin/python -I -B scripts/verify.py local` after source changes. `.github/ci-contract.json` owns six closed shards and identity. The authoring agent coordinates fresh same-origin review, separate creation witness and unedited receipt; initial admission and App activation remain distinct gates. Chaos Scheduler App4217367 alone approves and requests exact-head native squash. Never bypass controls or manipulate auto-merge. Source enrollments are disabled pending qualification.
