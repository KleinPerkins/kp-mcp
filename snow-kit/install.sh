#!/usr/bin/env bash
# install.sh — idempotent local install for the snow-kit MCP capability.
#
# Usage: install.sh [install|--stage-only|--check|--doctor|--repair|--uninstall]
# Browser SSO is always a separate operator step.
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
MCP_DIR="$(cd "$KIT_DIR/.." && pwd)"

log() { printf '[snow-kit/install] %s\n' "$*"; }

ACTION="${1:-install}"
case "$ACTION" in
  install|--stage-only|--check|--doctor|--repair|--uninstall) ;;
  *) log "ERROR: usage: install.sh [install|--stage-only|--check|--doctor|--repair|--uninstall]"; exit 2 ;;
esac

run_cli() { ( cd "$MCP_DIR" && uv run snow-kit "$@" ); }

if ! command -v uv >/dev/null 2>&1; then
  log "ERROR: uv not found on PATH"
  exit 1
fi

if [ "$ACTION" = "--uninstall" ]; then
  run_cli unregister
  log "done (registrations removed; local profile and Snowflake secure cache preserved)"
  exit 0
fi

if [ "$ACTION" = "--check" ]; then
  run_cli --help >/dev/null
  log "check OK"
  exit 0
fi

if [ "$ACTION" = "--doctor" ]; then
  run_cli doctor
  exit $?
fi

log "uv sync --locked (workspace at $MCP_DIR)"
( cd "$MCP_DIR" && uv sync --locked )
run_cli --help >/dev/null

if [ "$ACTION" = "--stage-only" ]; then
  log "staged (client configs unchanged)"
  exit 0
fi

if [ "$ACTION" = "--repair" ]; then
  run_cli repair
else
  run_cli setup
fi

log "done (profile + read-only registration reconciled; if setup reported needs_setup, rerun it with --account and --user, then run snow-kit auth login)"
