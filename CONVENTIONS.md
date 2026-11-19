# KleinPerkins MCP — Conventions

## Dev bootstrap

- `uv sync` (no flags) installs all three workspace members editable plus dev tooling (pytest, pyyaml).
- `uv run pytest -q` runs the full suite; `uv run python -m kp_mcp_testkit.editorial <paths>` runs the editorial lint.

## Core functions

- Every capability is a typed Python function: Pydantic `BaseModel` in, Pydantic `BaseModel` out.
- No `argparse`, no `print` in core; log to `stderr` via the structured logger.
- Output envelope: `{data, page, warnings, meta}` — see `google_kit.core.normalize`.

## Registry (single-core / dual-surface)

- Register each capability once: `OpSpec(name, fn, input_model, output_model, posture, scopes, …)`.
- CLI, MCP server, and docgen all derive from `google_kit.registry` — no adapter edits when adding a capability.

## Secrets

- macOS Keychain only (`KeychainSecretStore`). No plaintext fallback — fail loud (R15/B5).
- No secrets in platform configs (Cursor/Codex/Claude). Registrars write command + non-secret env only.

## Editorial discipline (R29)

- Remove stale content by subtraction; never comment out, never redirect to a superseded section.
- Phase-deferred behavior: `raise NotImplementedError("… (Phase N)")` + a real docstring.
- CI enforces: no commented-out code blocks, no duplicate headings, no stale-redirect phrases, line budget.

## Tests

- Unit tests live in `<package>/tests/`. Use `pytest` + `tmp_path` fixtures; no live network.
- Parity tests use `kp_mcp_testkit.parity.compare`; golden fixtures in `fixtures/golden/`.
- Fault injection uses `kp_mcp_testkit.faults.inject_fault_fn`.

## Adding a capability (summary)

1. Write the core function in `google_kit/core/<service>.py`.
2. Add an `OpSpec` entry in `google_kit/registry.py`.
3. CLI and MCP surfaces pick it up automatically (Phase 5+).
4. Run `uv run pytest -q` and editorial lint before committing.
