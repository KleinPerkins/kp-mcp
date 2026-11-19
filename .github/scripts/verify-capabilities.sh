#!/usr/bin/env bash
# .github/scripts/verify-capabilities.sh — self-contained CI gate for kp-capability/v1
# manifests in the kp-mcp monorepo. No ~/dev dependency.
#
# kp-mcp is an independently-governed sibling repo (its own uv-workspace layout); within it,
# capability artifacts sit FLAT at the repo root (today: google-kit/). For these, the eco
# scope paradigm uses a HARD-GATED explicit `scope:` field — kind:mcp MUST declare
# scope:global (no mcp/local partition exists). This script mirrors that gate so a regression
# in a manifest is caught remotely on push/PR, not only by LD running `make eco-verify`.
#
# Skipped (intentionally): packages whose pyproject.toml exists but that are not capability
# artifacts (kp-mcp-bootstrap, kp-mcp-testkit, widget-kit, template). A dir is a capability
# only if it carries a meta.yml declaring schema: kp-capability/v1.
set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
fail=0
note() { printf '%s\n' "$*"; }

found=0
seen_ids=""
for d in */; do
  m="${d}meta.yml"
  [ -f "$m" ] || continue
  grep -qE '^schema:[[:space:]]*kp-capability/v1' "$m" || continue
  found=1
  id_dir="${d%/}"
  idv="$(awk -F': *' '/^id:/{print $2; exit}' "$m" | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
  note "-- $id_dir/"
  # Required keys.
  for k in schema id kind flavor scope owner install; do
    grep -qE "^${k}:" "$m" || { note "  FAIL  missing key '$k'"; fail=1; }
  done
  # Kind.
  [ "$idv" = "$id_dir" ] && note "  PASS  id matches directory ($idv)" \
    || { note "  FAIL  id '$idv' does not match directory '$id_dir'"; fail=1; }
  case " $seen_ids " in
    *" $idv "*) note "  FAIL  duplicate capability id '$idv'"; fail=1 ;;
    *) seen_ids="$seen_ids $idv" ;;
  esac
  kind="$(awk -F': *' '/^kind:/{print $2; exit}' "$m" | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
  case "$kind" in
    skill|mcp|rule|tool|workflow|sub-agent|asset|doc) note "  PASS  kind $kind" ;;
    *) note "  FAIL  kind must be one of skill|mcp|rule|tool|workflow|sub-agent|asset|doc (got '$kind')"; fail=1 ;;
  esac
  # Flavor.
  flavor="$(awk -F': *' '/^flavor:/{print $2; exit}' "$m" | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
  case "$flavor" in 1|2) note "  PASS  flavor $flavor" ;; *) note "  FAIL  flavor must be 1|2 (got '$flavor')"; fail=1 ;; esac
  # Scope hard-gate: kind:mcp under this flat root MUST declare scope:global.
  scope="$(awk -F': *' '/^scope:/{print $2; exit}' "$m" | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
  if [ "$kind" = "mcp" ]; then
    [ "$scope" = "global" ] && note "  PASS  scope:global (gated for kind:mcp under flat root)" \
      || { note "  FAIL  kind:mcp must declare scope: global (got '$scope'); no mcp/local partition exists"; fail=1; }
  else
    case "$scope" in global|local) note "  PASS  scope $scope" ;; *) note "  FAIL  scope must be global|local (got '$scope')"; fail=1 ;; esac
  fi
  # install: bare filename, present, executable.
  inst="$(awk -F': *' '/^install:/{print $2; exit}' "$m" | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
  case "$inst" in
    "")        note "  FAIL  install contract missing (empty)"; fail=1 ;;
    *..*|*/*)  note "  FAIL  install must be a bare filename (got '$inst')"; fail=1 ;;
    *)
      if [ ! -f "${d}${inst}" ]; then note "  FAIL  install file ${d}${inst} missing"; fail=1
      elif [ ! -x "${d}${inst}" ]; then note "  FAIL  install file ${d}${inst} not executable"; fail=1
      else note "  PASS  install ${inst} present + executable"; fi ;;
  esac
done

if [ "$found" = 0 ]; then
  note "verify-capabilities: NO kp-capability/v1 manifests found at repo root (FAIL)"; exit 1
fi

# Lockfile parity (WF1/B2, Decision D1=keep): .eco-registry.lock must match the current metas. Local/CI
# fast-feedback gate of record; branch protection can require it only where the GitHub plan exposes it.
# eco-lock.sh is the single normalization algorithm; the pre-commit registration-guard regenerates the
# lock, CI is the backstop.
if [ -x .github/scripts/eco-lock.sh ]; then
  if ! bash .github/scripts/eco-lock.sh check; then note "FAIL  .eco-registry.lock parity"; fail=1; fi
else
  note "FAIL  .github/scripts/eco-lock.sh missing (cannot verify lock parity)"; fail=1
fi

# Pure native style planning has no account, network or dependency requirements.
# Keep its exact-target/revision/tab refusal checks in this required owner job.
if ! python3 -B google-kit/tests/test_native_doc_styles.py -v; then
  note "FAIL  native Google Docs style contract"
  fail=1
fi

# The personal enrollment/storage contract is stdlib-only and fixture-only.
# Real registry/CLI integration is also qualified in the package suites; this
# gate does not substitute for excluded cross-kit or native Keychain evidence.
if ! python3 -I -S -B kp-mcp-bootstrap/tests/personal_auth_contract.py; then
  note "FAIL  personal Google authentication/storage contract"
  fail=1
fi

if [ "$fail" = 0 ]; then note "verify-capabilities: OK"; else note "verify-capabilities: FAILED"; exit 1; fi
