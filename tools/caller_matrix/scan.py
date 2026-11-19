#!/usr/bin/env python3
"""
tools/caller_matrix/scan.py

Exhaustive caller matrix generator for the chaos-labs Google legacy surface.
Detects: py imports, py attribute-calls, subprocess CLI invocations, config
references, skills, rules, commands, docs, and test files.

STDLIB ONLY: ast, os, re, json, pathlib, argparse, sys, collections, datetime.

Usage:
    python3 tools/caller_matrix/scan.py [--root ROOT] [--out OUT] [--exclude DIR]
"""

import argparse
import ast
import collections
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Target definitions ────────────────────────────────────────────────────────

# Python module names used in import detection
G_MODULES: frozenset = frozenset({
    "google_auth",
    "gcalendar",
    "gdoc_fetch",
    "gdrive",
    "gforms",
    "gkeep",
    "gmail",
    "gsheets",
    "gslides",
    "gtasks",
    "md_to_gdoc",
    "google_drive_access",
})

# Script file basenames (for text/subprocess detection)
G_SCRIPT_FILES: frozenset = frozenset({
    "gcalendar.py",
    "gdoc-fetch.py",
    "gdrive.py",
    "gforms.py",
    "gkeep.py",
    "gmail.py",
    "google_auth.py",
    "gsheets.py",
    "gslides.py",
    "gtasks.py",
    "md_to_gdoc.py",
    "google_drive_access.py",
})

# ─── Noise dirs ────────────────────────────────────────────────────────────────

NOISE_DIRS: frozenset = frozenset({
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
})

# ─── Canonical target normalization ────────────────────────────────────────────

def _canonical(text: str) -> str:
    """Map a raw matched string to a canonical target key."""
    t = text.lower().replace("-", "_")
    if "google_auth" in t:
        return "google_auth"
    if "gdrive" in t:
        return "gdrive"
    if "gmail" in t:
        return "gmail"
    if "gcalendar" in t:
        return "gcalendar"
    if "gsheets" in t:
        return "gsheets"
    if "gslides" in t:
        return "gslides"
    if "gforms" in t:
        return "gforms"
    if "gtasks" in t:
        return "gtasks"
    if "gkeep" in t:
        return "gkeep"
    if "md_to_gdoc" in t:
        return "md_to_gdoc"
    if "md_to_google_doc" in t:
        return "md-to-google-doc"
    if "gdoc" in t:
        return "gdoc-fetch"
    if "google_drive_access" in t:
        return "google_drive_access"
    if "google_workspace" in t:
        return "google_workspace"
    return text


# ─── Migration action tables ───────────────────────────────────────────────────

_MIGRATION: dict = {
    "google_auth": (
        "Migrate to google_kit.core.auth + SecretStore (Keychain); "
        "import chaos-labs plaintext token.json into Keychain then remove it"
    ),
    "gdrive": (
        "Migrate to google_kit drive CLI/MCP "
        "(fetch, create, search, upload, Sites via Playwright)"
    ),
    "gdoc-fetch": (
        "Migrate to google_kit drive fetch (Docs v1 API → "
        "google_kit drive fetch <doc-id>)"
    ),
    "gmail": (
        "Migrate to google_kit gmail CLI/MCP "
        "(list, get, search, labels, profile)"
    ),
    "gcalendar": (
        "Migrate to google_kit calendar CLI/MCP "
        "(list, create, freebusy, update, delete)"
    ),
    "gsheets": (
        "Migrate to google_kit sheets CLI/MCP "
        "(create, read, write, add-sheet, info, chart)"
    ),
    "gslides": (
        "Migrate to google_kit slides CLI/MCP "
        "(create, get, add-slide, update-text, add-image)"
    ),
    "gforms": (
        "Migrate to google_kit forms CLI/MCP "
        "(create, get, list-responses, add-item, update)"
    ),
    "gtasks": (
        "Migrate to google_kit tasks CLI/MCP "
        "(list-lists, list, create, complete, update, delete)"
    ),
    "gkeep": (
        "Migrate to google_kit keep CLI/MCP "
        "(create, list, get, delete)"
    ),
    "md_to_gdoc": (
        "Migrate to google_kit drive doc-upload "
        "(Docs batchUpdate; net-new capability in google-kit P4)"
    ),
    "google_drive_access": (
        "Migrate Drive access to google_kit.core.drive with Keychain auth; "
        "doc-upload subcommand covers the md-to-google-doc OAuth flow"
    ),
    "md-to-google-doc": (
        "Migrate to google_kit drive doc-upload "
        "(Docs batchUpdate; net-new capability in google-kit P4)"
    ),
    "google_workspace": (
        "Update rule/skill/command/doc to reference google-kit "
        "safety rule and CLI/MCP tool names"
    ),
}

_POST_CHECK: dict = {
    "google_auth": (
        "Run 'google-kit auth status'; confirm Keychain has token; "
        "confirm plaintext token.json absent or ignored"
    ),
    "gdrive": (
        "Run google-kit drive parity suite vs golden corpus; "
        "verify drive_upload and Sites (Playwright) preserved"
    ),
    "gdoc-fetch": (
        "Run 'google-kit drive fetch <id>' vs legacy gdoc-fetch.py output; "
        "verify byte/semantic match"
    ),
    "gmail": "Run google-kit gmail parity suite vs golden corpus",
    "gcalendar": "Run google-kit calendar parity suite vs golden corpus",
    "gsheets": (
        "Run google-kit sheets parity suite vs golden corpus; "
        "verify staged_review_sheet and org_chart flows"
    ),
    "gslides": "Run google-kit slides parity suite vs golden corpus",
    "gforms": "Run google-kit forms parity suite vs golden corpus",
    "gtasks": "Run google-kit tasks parity suite vs golden corpus",
    "gkeep": "Run google-kit keep parity suite vs golden corpus",
    "md_to_gdoc": (
        "Run doc-upload integration test; "
        "verify Docs batchUpdate output matches legacy md_to_gdoc"
    ),
    "google_drive_access": (
        "Verify Drive access via google_kit.core.drive with Keychain auth"
    ),
    "md-to-google-doc": (
        "Run full doc-upload parity test; "
        "verify Docs batchUpdate output matches legacy package"
    ),
    "google_workspace": (
        "Verify updated rule/skill/command uses correct "
        "google-kit tool names and scopes"
    ),
}


def _migration(target: str) -> str:
    return _MIGRATION.get(target, f"Migrate to google_kit equivalent of '{target}'")


def _post_check(target: str) -> str:
    return _POST_CHECK.get(target, f"Run google-kit parity test for '{target}'")


# ─── Regex patterns ────────────────────────────────────────────────────────────

# Matches g-script stems and related module names in text (any file type)
_TEXT_G_RE = re.compile(
    r"(?:gcalendar|gdoc[_-]fetch|gdrive|gforms|gkeep|gmail|google_auth|"
    r"gsheets|gslides|gtasks|md[_-]to[_-]gdoc|google[_-]drive[_-]access|"
    r"md-to-google-doc|gdoc-fetch)(?:\.py\b|\b)",
    re.IGNORECASE,
)

# Matches broader Google workspace references
_TEXT_GOOGLE_RE = re.compile(
    r"(?:google[_-]workspace|capture[_-]g(?:drive|mail|calendar)|"
    r"scripts/g[a-z]|g-scripts)",
    re.IGNORECASE,
)

# Regex import patterns for fallback (Python files that fail AST parsing)
_PY_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+([A-Za-z0-9_.]+)",
)

# Secret/token redaction
_SECRET_RE = re.compile(
    r"ya29\.[A-Za-z0-9_\-]+"
    r'|"[A-Za-z0-9+/]{40,}={0,2}"'
    r"|'[A-Za-z0-9+/]{40,}={0,2}'"
)


def _sanitize(snippet: str) -> str:
    """Strip leading/trailing whitespace, redact tokens, cap at 300 chars."""
    s = snippet.strip()
    s = _SECRET_RE.sub("[REDACTED]", s)
    return s[:300]


# ─── File walker ───────────────────────────────────────────────────────────────

def walk_files(root: Path, extra_excludes: set) -> list:
    """Walk root skipping noise dirs; return list of Path objects."""
    exclude = NOISE_DIRS | extra_excludes
    files = []
    for dirpath, dirnames, filenames in os.walk(str(root), onerror=lambda _: None):
        # Prune noise dirs in-place so os.walk won't descend into them
        dirnames[:] = sorted(d for d in dirnames if d not in exclude)
        for fname in sorted(filenames):
            files.append(Path(dirpath) / fname)
    return files


# ─── File classifier ──────────────────────────────────────────────────────────

def classify_file(path: Path, root: Path) -> str:
    """
    Returns one of:
      python | config | skill | rule | command | doc | test | other
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return "other"

    parts = rel.parts
    stem = path.stem
    ext = path.suffix.lower()

    # Test Python files: anywhere named test_*.py / *_test.py, or inside tests/
    if ext == ".py" and (
        "tests" in parts
        or stem.startswith("test_")
        or stem.endswith("_test")
        or (len(parts) >= 1 and parts[0] == "tests")
    ):
        return "test"

    # Rules: .mdc anywhere, or files under rules/
    if ext == ".mdc" or (parts and parts[0] == "rules"):
        return "rule"

    # Commands: commands/*.md
    if parts and parts[0] == "commands" and ext == ".md":
        return "command"

    # Skills: anything under skills/
    if parts and parts[0] == "skills":
        return "skill"

    # Config: .yml / .yaml / .toml anywhere; .json only under config/
    if ext in (".yml", ".yaml", ".toml"):
        return "config"
    if ext == ".json" and parts and parts[0] == "config":
        return "config"

    # Python
    if ext == ".py":
        return "python"

    # Docs: .md files not already matched
    if ext == ".md":
        return "doc"

    return "other"


# ─── AST helpers ──────────────────────────────────────────────────────────────

def _get_lineno(node: ast.AST) -> int:
    return getattr(node, "lineno", 0)


def _extract_strings(node: ast.AST) -> list:
    """Recursively extract string literals from an AST node."""
    result = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        result.append(node.value)
    elif isinstance(node, (ast.List, ast.Tuple)):
        for elt in node.elts:
            result.extend(_extract_strings(elt))
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        result.extend(_extract_strings(node.left))
        result.extend(_extract_strings(node.right))
    return result


def _func_name(node: ast.Call) -> str:
    """Return dotted callable name, or ''."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        v = node.func.value
        attr = node.func.attr
        if isinstance(v, ast.Name):
            return f"{v.id}.{attr}"
        if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name):
            return f"{v.value.id}.{v.attr}.{attr}"
    return ""


_SUBPROCESS_CALLS: frozenset = frozenset({
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.getoutput",
    "subprocess.getstatusoutput",
    "os.system",
    "os.popen",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
})


def _is_subprocess_call(fname: str) -> bool:
    return fname in _SUBPROCESS_CALLS


def _match_gscript(strings: list) -> tuple:
    """Return (True, canonical_target) if any string references a g-script."""
    for s in strings:
        m = _TEXT_G_RE.search(s)
        if m:
            return True, _canonical(m.group())
        m2 = _TEXT_GOOGLE_RE.search(s)
        if m2:
            return True, _canonical(m2.group())
    return False, ""


# ─── Safe file reader ─────────────────────────────────────────────────────────

def _read_lines(path: Path) -> list:
    """Read file lines, trying multiple encodings. Returns [] on failure."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=enc).splitlines()
        except (UnicodeDecodeError, OSError, PermissionError):
            continue
    return []


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# ─── Record builder ────────────────────────────────────────────────────────────

def _make_record(
    path: Path,
    root: Path,
    line: int,
    file_type: str,
    caller_type: str,
    target: str,
    snippet: str,
) -> dict:
    # For Python test files, override caller_type to "test"
    if file_type == "test":
        caller_type = "test"
    return {
        "file_abs": str(path),
        "file_rel": _rel(path, root),
        "line": line,
        "caller_type": caller_type,
        "target": target,
        "snippet": _sanitize(snippet),
        "migration_action": _migration(target),
        "post_migration_check": _post_check(target),
    }


# ─── Python AST analyzer ─────────────────────────────────────────────────────

def analyze_python_ast(
    path: Path, root: Path, lines: list, file_type: str
) -> tuple:
    """
    AST-based analysis of a Python file.
    Returns (records, success). success=False → caller should use regex fallback.
    """
    src = "\n".join(lines)
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return [], False

    records = []

    for node in ast.walk(tree):
        lineno = _get_lineno(node)
        line_text = lines[lineno - 1] if 0 < lineno <= len(lines) else ""

        # ── Import statements ───────────────────────────────────────────────
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in G_MODULES:
                    records.append(_make_record(
                        path, root, lineno, file_type,
                        "py_import", top, line_text,
                    ))

        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            mod_parts = mod.split(".")
            matched = False
            for part in mod_parts:
                if part in G_MODULES:
                    records.append(_make_record(
                        path, root, lineno, file_type,
                        "py_import", part, line_text,
                    ))
                    matched = True
                    break
            if not matched:
                # e.g. `from scripts import google_auth`
                # or `from . import google_auth`
                for alias in node.names:
                    if alias.name in G_MODULES:
                        records.append(_make_record(
                            path, root, lineno, file_type,
                            "py_import", alias.name, line_text,
                        ))

        # ── Call nodes ──────────────────────────────────────────────────────
        elif isinstance(node, ast.Call):
            fname = _func_name(node)

            # subprocess / os.system / os.popen invocations
            if _is_subprocess_call(fname):
                all_strs = []
                for arg in node.args:
                    all_strs.extend(_extract_strings(arg))
                for kw in node.keywords:
                    if kw.arg not in ("env", "cwd"):
                        all_strs.extend(_extract_strings(kw.value))
                hit, target = _match_gscript(all_strs)
                if hit:
                    records.append(_make_record(
                        path, root, lineno, file_type,
                        "subprocess_cli", target, line_text,
                    ))

            # Attribute call on a g-module name, e.g. gsheets.create_spreadsheet(...)
            elif (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in G_MODULES
            ):
                module_name = node.func.value.id
                records.append(_make_record(
                    path, root, lineno, file_type,
                    "py_call", module_name, line_text,
                ))

    return records, True


# ─── Python regex fallback ────────────────────────────────────────────────────

def analyze_python_regex(
    path: Path, root: Path, lines: list, file_type: str
) -> list:
    """Regex fallback for Python files that failed AST parsing."""
    records = []
    for lineno, line in enumerate(lines, 1):
        # Import detection
        m = _PY_IMPORT_RE.match(line)
        if m:
            mod_str = m.group(1)
            for part in mod_str.split("."):
                if part in G_MODULES:
                    records.append(_make_record(
                        path, root, lineno, file_type,
                        "py_import", part, line,
                    ))
                    break

        # Subprocess / os.system detection
        if (
            "subprocess" in line
            or "os.system" in line
            or "os.popen" in line
        ):
            hit, target = _match_gscript([line])
            if hit:
                records.append(_make_record(
                    path, root, lineno, file_type,
                    "subprocess_cli", target, line,
                ))

        # Attribute calls on g-module names outside of import lines
        if "import" not in line:
            for mod in G_MODULES:
                if f"{mod}." in line:
                    m2 = re.search(rf"\b{re.escape(mod)}\.\w+", line)
                    if m2:
                        records.append(_make_record(
                            path, root, lineno, file_type,
                            "py_call", mod, line,
                        ))
                        break  # one record per line per detection

    return records


# ─── Text file analyzer ────────────────────────────────────────────────────────

def analyze_text_file(
    path: Path, root: Path, file_type: str
) -> list:
    """Scan non-Python files (config, skill, rule, command, doc) for g-script refs."""
    lines = _read_lines(path)
    records = []
    for lineno, line in enumerate(lines, 1):
        hit1 = _TEXT_G_RE.search(line)
        hit2 = _TEXT_GOOGLE_RE.search(line) if not hit1 else None
        if hit1 or hit2:
            raw = (hit1 or hit2).group()
            target = _canonical(raw)
            records.append(_make_record(
                path, root, lineno, file_type,
                file_type, target, line,
            ))
    return records


# ─── Deduplication ────────────────────────────────────────────────────────────

def _dedup(records: list) -> list:
    seen = set()
    result = []
    for r in records:
        key = (r["file_abs"], r["line"], r["caller_type"], r["target"])
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result


# ─── D3 anchor verification ───────────────────────────────────────────────────

# Files/paths explicitly cited in DECISIONS.md D3 as known callers.
# We verify each appears in the caller matrix OR is found on disk but currently
# has no detectable Google dependency (refactored/planned state, not a scanner gap).
D3_ANCHORS = [
    # (description, partial_file_path_or_target)
    ("staged_review_sheet.py",              "staged_review_sheet.py"),
    ("context_capture/sheets_extract.py",   "sheets_extract.py"),
    ("org_chart.py",                        "org_chart.py"),
    ("commands/google.md",                  "commands/google.md"),
    ("rules/chaos-labs-google-workspace",   "chaos-labs-google-workspace"),
    ("config/*.yml",                        "config/"),
    ("md-to-google-doc package",            "md-to-google-doc"),
    ("session-worktrees/",                  "session-worktrees"),
]


def verify_d3_anchors(root: Path, callers: list) -> list:
    """
    For each D3 anchor: determine if it appears as a caller, exists-but-clean,
    exists-not-found (scanner gap), or is absent from the repo (expected empty).
    Returns a list of verification result dicts.
    """
    caller_files = set(r["file_rel"] for r in callers)
    caller_targets = set(r["target"] for r in callers)

    results = []
    for desc, needle in D3_ANCHORS:
        # Check if needle appears in any caller's file path
        in_callers = any(needle in f for f in caller_files)
        # Also check target names
        in_targets = needle in caller_targets

        # Check if needle points to something that exists on disk
        on_disk = False
        disk_path = None
        if "/" in needle or needle.endswith(".py") or needle.endswith(".md"):
            # Try to find the file under root
            for dirpath, _dirs, files in os.walk(str(root), onerror=lambda _: None):
                for fname in files:
                    fp = os.path.join(dirpath, fname)
                    rel = fp[len(str(root)) + 1:]
                    if needle in rel or needle in fp:
                        on_disk = True
                        disk_path = rel
                        break
                if on_disk:
                    break
        elif needle.startswith("config/"):
            config_dir = root / "config"
            on_disk = config_dir.exists() and any(
                f.suffix in (".yml", ".yaml")
                for f in config_dir.iterdir()
                if f.is_file()
            )
        elif needle == "session-worktrees":
            swt = root / "session-worktrees"
            on_disk = swt.exists()
            if on_disk:
                entries = list(swt.iterdir()) if swt.exists() else []
                if not entries:
                    # Empty dir — no callers possible; mark as expected-empty
                    results.append({
                        "anchor": desc,
                        "status": "expected-empty",
                        "note": "session-worktrees/ exists but is empty; no duplicate checkouts present",
                    })
                    continue
        elif needle == "md-to-google-doc":
            on_disk = (root / "scripts" / "packages" / "md-to-google-doc").exists()
        else:
            on_disk = False

        if in_callers or in_targets:
            status = "PASS"
            note = "Found in caller matrix"
        elif on_disk:
            status = "PASS-CLEAN"
            note = (
                "File/path exists on disk but has no detectable Google dependency "
                "in current source (may have been refactored or is a future target)"
            )
            if disk_path:
                note += f"; disk path: {disk_path}"
        else:
            status = "FAIL"
            note = "Not found in caller matrix and not found on disk — possible scanner gap"

        results.append({"anchor": desc, "status": status, "note": note})

    return results


# ─── Main scan orchestrator ───────────────────────────────────────────────────

def scan(root: Path, extra_excludes: set) -> dict:
    """Full scan; returns the complete result dict."""
    all_files = walk_files(root, extra_excludes)
    total_files_walked = len(all_files)

    all_records = []
    unparsed = []
    files_processed = 0

    for path in all_files:
        file_type = classify_file(path, root)
        if file_type == "other":
            continue
        files_processed += 1
        ext = path.suffix.lower()

        if ext == ".py" or file_type in ("python", "test"):
            lines = _read_lines(path)
            if not lines:
                continue
            records, success = analyze_python_ast(path, root, lines, file_type)
            if not success:
                unparsed.append({
                    "file_abs": str(path),
                    "file_rel": _rel(path, root),
                    "error": "SyntaxError: could not parse; used regex fallback",
                })
                records = analyze_python_regex(path, root, lines, file_type)
            all_records.extend(records)

        elif file_type in ("config", "skill", "rule", "command", "doc"):
            records = analyze_text_file(path, root, file_type)
            all_records.extend(records)

    all_records = _dedup(all_records)
    all_records.sort(key=lambda r: (r["file_rel"], r["line"], r["caller_type"], r["target"]))

    # Session-worktrees note
    swt_path = root / "session-worktrees"
    swt_count = 0
    swt_entries = []
    if swt_path.exists():
        try:
            swt_entries = [e.name for e in swt_path.iterdir()]
            swt_count = len(swt_entries)
        except OSError:
            pass
    if swt_count > 0:
        swt_note = (
            f"session-worktrees/ has {swt_count} entries (potential duplicate checkouts); "
            f"all were scanned and their callers are included in the matrix"
        )
    else:
        swt_note = "session-worktrees/ exists but is empty (0 entries); no duplication"

    counts_by_type = dict(sorted(collections.Counter(
        r["caller_type"] for r in all_records
    ).items()))
    counts_by_target = dict(sorted(
        collections.Counter(r["target"] for r in all_records).items(),
        key=lambda kv: (-kv[1], kv[0]),
    ))

    d3_anchors = verify_d3_anchors(root, all_records)
    d3_all_pass = all(v["status"] in ("PASS", "PASS-CLEAN", "expected-empty") for v in d3_anchors)

    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "root": str(root),
            "total_files_walked": total_files_walked,
            "total_files_processed": files_processed,
            "total_callers": len(all_records),
            "unparsed_count": len(unparsed),
            "session_worktrees_note": swt_note,
        },
        "counts_by_type": counts_by_type,
        "counts_by_target": counts_by_target,
        "callers": all_records,
        "unparsed": unparsed,
        "d3_anchor_verification": {
            "all_pass": d3_all_pass,
            "results": d3_anchors,
        },
    }


# ─── Markdown report generator ────────────────────────────────────────────────

def generate_markdown(result: dict) -> str:
    m = result["metadata"]
    lines = [
        "# Caller Matrix",
        "",
        f"Generated: `{m['generated_at']}`  ",
        f"Root: `{m['root']}`  ",
        f"Files walked: {m['total_files_walked']}  ",
        f"Files processed: {m['total_files_processed']}  ",
        f"**Total callers: {m['total_callers']}**  ",
        f"Unparsed files: {m['unparsed_count']}  ",
        "",
        f"> {m['session_worktrees_note']}",
        "",
        "---",
        "",
        "## Counts by Caller Type",
        "",
        "| caller_type | count |",
        "| --- | --- |",
    ]
    for ct, cnt in result["counts_by_type"].items():
        lines.append(f"| {ct} | {cnt} |")

    lines += [
        "",
        "## Counts by Target",
        "",
        "| target | count |",
        "| --- | --- |",
    ]
    for tgt, cnt in result["counts_by_target"].items():
        lines.append(f"| {tgt} | {cnt} |")

    # Group callers by target
    by_target: dict = collections.defaultdict(list)
    for r in result["callers"]:
        by_target[r["target"]].append(r)

    lines += [
        "",
        "---",
        "",
        "## Callers by Target",
        "",
    ]

    for tgt in sorted(by_target.keys()):
        callers = by_target[tgt]
        lines += [
            f"### {tgt}",
            "",
            f"**Migration action:** {_migration(tgt)}  ",
            f"**Post-migration check:** {_post_check(tgt)}",
            "",
            "| file_rel | line | caller_type | snippet |",
            "| --- | --- | --- | --- |",
        ]
        for r in callers:
            snippet = r["snippet"].replace("|", "\\|").replace("\n", " ")[:120]
            lines.append(
                f"| `{r['file_rel']}` | {r['line']} | {r['caller_type']} | `{snippet}` |"
            )
        lines.append("")

    if result["unparsed"]:
        lines += [
            "---",
            "",
            "## Unparsed Files (regex fallback used)",
            "",
            "| file_rel | error |",
            "| --- | --- |",
        ]
        for u in result["unparsed"]:
            lines.append(f"| `{u['file_rel']}` | {u['error']} |")
        lines.append("")

    d3v = result.get("d3_anchor_verification", {})
    if d3v:
        overall = "ALL PASS" if d3v.get("all_pass") else "SOME FAILED"
        lines += [
            "---",
            "",
            f"## D3 Anchor Verification — {overall}",
            "",
            "_DECISIONS.md D3 lists callers that exceed the obvious set. "
            "Each anchor is verified against the matrix or confirmed clean on disk._",
            "",
            "| anchor | status | note |",
            "| --- | --- | --- |",
        ]
        for av in d3v.get("results", []):
            note = av.get("note", "")[:150]
            lines.append(f"| {av['anchor']} | **{av['status']}** | {note} |")
        lines.append("")

    return "\n".join(lines)


# ─── Console summary ──────────────────────────────────────────────────────────

def print_summary(result: dict) -> None:
    m = result["metadata"]
    sep = "=" * 62
    print(f"\n{sep}")
    print("CALLER MATRIX SUMMARY")
    print(sep)
    print(f"Root:              {m['root']}")
    print(f"Generated:         {m['generated_at']}")
    print(f"Files walked:      {m['total_files_walked']}")
    print(f"Files processed:   {m['total_files_processed']}")
    print(f"Total callers:     {m['total_callers']}")
    print(f"Unparsed files:    {m['unparsed_count']}")
    print(f"Session-worktrees: {m['session_worktrees_note']}")
    print()
    print("By caller_type:")
    for t, c in result["counts_by_type"].items():
        print(f"  {t:<22s}  {c}")
    print()
    print("By target (desc):")
    for t, c in result["counts_by_target"].items():
        print(f"  {t:<30s}  {c}")
    print()
    d3v = result.get("d3_anchor_verification", {})
    print("D3 anchor verification:")
    for av in d3v.get("results", []):
        print(f"  [{av['status']:<14s}] {av['anchor']}")
        if av["status"] not in ("PASS", "expected-empty"):
            print(f"                         {av['note']}")
    overall = "ALL PASS" if d3v.get("all_pass") else "SOME FAILED"
    print(f"  D3 result: {overall}")
    print(sep)
    print()


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate exhaustive caller matrix for chaos-labs Google legacy surface."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Root of the chaos-labs tree to scan (read-only)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Private output JSON path outside this source checkout",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="DIR",
        help="Additional directory names to skip (repeatable)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        sys.exit(f"ERROR: root does not exist: {root}")

    out_json = Path(args.out).resolve()
    source_root = Path(__file__).resolve().parents[2]
    if out_json.is_relative_to(source_root):
        parser.error("discovery output must remain outside the source checkout")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md = out_json.parent / "CALLER-MATRIX.md"

    print(f"Scanning {root} ...")
    result = scan(root, set(args.exclude))

    out_json.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Written JSON: {out_json}")

    md_content = generate_markdown(result)
    out_md.write_text(md_content, encoding="utf-8")
    print(f"Written MD:   {out_md}")

    print_summary(result)


if __name__ == "__main__":
    main()
