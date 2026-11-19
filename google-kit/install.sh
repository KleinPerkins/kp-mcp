#!/usr/bin/env bash
# install.sh — idempotent local install for the google-kit MCP capability (flavor 1).
#
# Two halves, both required to make google-kit usable on a machine:
#   CLI : ensure the `google-kit` console-script entrypoint exists by syncing the
#         kp-mcp uv workspace (idempotent; no-op if already synced).
#   MCP : register the stdio server with the agent platforms (Cursor / Codex / Claude)
#         by calling the kit's own `google-kit bootstrap` verb — non-secret command +
#         args only; atomic write with timestamped backup per the registrar contract.
#   Docs: repair the user-level doc-styles store with a blank starter profile.
#
# Never writes secrets. Never runs interactive OAuth (auth is a separate operator
# step: `google-kit auth login`). Safe to re-run.
#
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # .../capabilities/mcp/google-kit
MCP_DIR="$(cd "$KIT_DIR/.." && pwd)"                          # .../capabilities/mcp (uv workspace root)

log() { printf '[google-kit/install] %s\n' "$*"; }

# 1. CLI — build/refresh the venv entrypoint (idempotent; no-op if already synced).
if command -v uv >/dev/null 2>&1; then
  log "uv sync (workspace at $MCP_DIR)"
  ( cd "$MCP_DIR" && uv sync )
else
  log "WARN: uv not found on PATH — cannot build CLI entrypoint; skipping CLI step"
fi

# 2. MCP — register the stdio server with Cursor/Codex/Claude (idempotent).
if ( cd "$MCP_DIR" && uv run google-kit --help >/dev/null 2>&1 ); then
  log "google-kit bootstrap (registering MCP server with platforms)"
  ( cd "$MCP_DIR" && uv run google-kit bootstrap )
else
  log "WARN: google-kit CLI not available; skipped MCP registration"
fi

log "done (no secrets written; doc-styles repaired; run 'google-kit auth login' separately to authorize)"
